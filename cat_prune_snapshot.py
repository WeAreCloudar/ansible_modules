#!/usr/bin/python

DOCUMENTATION = '''
module: cat_prune_snapshot
short_description: Prune snapshots from EC2 instances with an automation tag
description:
  - Prune snapshots from EC2 instances with an automation tag
version_added: null
author: Ben Bridts
notes:
  - Remember that all times are UTC
  - This module is trigger based, not state based, you should set the grace period in function of the interval between runs.
requirements:
  - the boto-python package
options:
  aws_secret_key:
    description:
      - AWS secret key. If not set then the value of the AWS_SECRET_KEY environment variable is used.
    required: false
    default: null
    aliases: [ 'ec2_secret_key', 'secret_key' ]
    version_added: "1.5"
  aws_access_key:
    description:
      - AWS access key. If not set then the value of the AWS_ACCESS_KEY environment variable is used.
    required: false
    default: null
    aliases: [ 'ec2_access_key', 'access_key' ]
    version_added: "1.5"
  region:
    description:
      - The AWS region to use. If not specified then the value of the EC2_REGION environment variable, if any, is used.
    required: false
    aliases: ['aws_region', 'ec2_region']
    version_added: "1.5"
  tag:
    description:
      - The tag where the automation JSON is stored
    required: false
    default: CAT
  grace:
    description:
      - The maximum number of minutes after the defined time that the action should still be triggered.
    required: false
    default: 10
'''

EXAMPLES = '''
# Note: None of these examples set aws_access_key, aws_secret_key, or region.
# It is assumed that their matching environment variables are set.

# Basic example
- cat_prune_snapshot:
    tag: CAT
'''

from datetime import datetime, timedelta

try:
    import boto.ec2
except ImportError:
    print "failed=True msg='boto required for this module'"
    sys.exit(1)

# Default values
AUTOMATION_TAG = 'CAT'

# Constants
DAYS_IN_YEAR = 365.25
DAYS_IN_WEEK = 7
DAYS_IN_MONTH = DAYS_IN_YEAR / 12


def main():
    # Output
    changed = False
    pruned_snapshots = []
    kept_snapshots = []

    # Input
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        tag=dict(required=False, default=AUTOMATION_TAG),
    ))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    automation_tag = module.params.get('tag', AUTOMATION_TAG)

    # Get the current time
    now = datetime.utcnow()

    # Get all the instances and snapshots with an automation tag
    conn = ec2_connect(module)
    filters = {
        'tag-key': automation_tag
    }
    all_instances = conn.get_only_instances(filters=filters)
    all_snapshots = conn.get_all_snapshots(filters=filters)

    # Group snapshots per instances and add more attributes from the automation tag
    grouped_snapshots = {}
    for snapshot in all_snapshots:
        snapshot.automation = json.loads(snapshot.tags[automation_tag])
        try:
            snapshot.prune = snapshot.automation['prune']
        except KeyError:
            snapshot.prune = False
        snapshot.start_datetime = datetime.strptime(snapshot.start_time, '%Y-%m-%dT%H:%M:%S.%fZ')

        try:
            grouped_snapshots[snapshot.volume_id].append(snapshot)
        except KeyError:
            grouped_snapshots[snapshot.volume_id] = [snapshot]

    # Loop over all instances
    for instance in all_instances:
        instance.automation = json.loads(instance.tags[automation_tag])
        try:
            retention = instance.automation['ret']
        except KeyError:
            # no retention policy, Move on to next instance
            continue

        '''
        What this does:

        - We make a list of all the times we need a snapshot for and another list of all the snapshots we have.
        - For every time we need:
            - If there are no older snapshots, keep the oldest available snapshot
            - If there are older snapshots, keep the newest
        - Older times get to choose the best fitting snapshot first. And every snapshot can be used only once. When
          there aren't enough snapshots yet, younger times will not have a corresponding snapshot yet, even if there is
          an exact match (bit it will be kept either way, because it is the best fit for an older snapshot)
        '''

        # Get all the times there should be a snapshot
        keep_times = []
        try:
            for i in range(1, int(retention['d'])):
                keep_times.append(now - timedelta(days=1 * i))
        except KeyError:
            pass
        try:
            for i in range(1, int(retention['w'])):
                keep_times.append(now - timedelta(days=DAYS_IN_WEEK * i))
        except KeyError:
            pass
        try:
            for i in range(1, int(retention['m'])):
                keep_times.append(now - timedelta(days=DAYS_IN_MONTH * i))
        except KeyError:
            pass
        try:
            for i in range(1, int(retention['y'])):
                keep_times.append(now - timedelta(days=DAYS_IN_YEAR * i))
        except KeyError:
            pass

        # Sort the times. We sort from newest to oldest, because we're going to use it as a stack
        keep_times.sort(reverse=True)

        # Repeat for every volume of the instance
        for dev, mapping_type in instance.block_device_mapping.items():
            # Copy the keep times, so we can use it as stack (and pop the oldest time)
            keep_times_stack = keep_times[:]
            # Reset finished indicator
            finished_keep_times = False

            # Find snapshots for this volume
            volume_id = mapping_type.volume_id
            try:
                snapshots = grouped_snapshots[volume_id]
            except KeyError:
                # no snapshots for volume
                continue

            # Sort the snapshots (oldest first)
            snapshots.sort(key=lambda x: x.start_time, reverse=False)

            # Get the oldest keep_time
            try:
                current_keep_time = keep_times_stack.pop()
            except IndexError:
                finished_keep_times = True

            snapshot_amount = len(snapshots)

            # Loop through the snapshots, from old to new.
            for i, snapshot in enumerate(snapshots):
                if finished_keep_times:
                    # We don't need to keep any more backups
                    keep = False
                    reason = 'delete, we have all the snapshots we need'
                elif i < snapshot_amount - 1:
                    # We still need a snapshot and there are at least two left
                    newer_snapshot = snapshots[i + 1]

                    if snapshot.start_datetime >= current_keep_time:
                        # Current snapshot is newer then keep time. Always keep.
                        keep = True
                        reason = 'keep, younger than keep_time %s and no older snapshot left' % current_keep_time.isoformat()
                    elif newer_snapshot.start_datetime >= current_keep_time:
                        # Next snapshot is newer than keep time. This one is the most recent, but older than keep time
                        keep = True
                        reason = 'keep, best fit for keep_time %s' % current_keep_time.isoformat()
                    else:
                        # The next snapshot should be a better fit
                        keep = False
                        reason = 'delete, because the next one is newer'

                else:  # i >= snapshot_amount - 1
                    # Need more backups, but this is the last one
                    keep = True
                    reason = 'keep, it is the last one, and we need more snapshots'

                if keep:  # We found a snapshot for the current keep time
                    kept_snapshots.append({
                        'snapshot_id': snapshot.id,
                        'snapshot_time': snapshot.start_datetime.isoformat(),
                        'volume_id': volume_id,
                        'instance_id': instance.id,
                        'reason': reason,
                        'keep_time': current_keep_time.isoformat()
                    })
                    try:
                        # Try getting the next keep time
                        current_keep_time = keep_times_stack.pop()
                    except IndexError:
                        # No more times, so we're finished (delete all snapshots we haven't processed yet)
                        finished_keep_times = True

                elif not snapshot.prune:
                    kept_snapshots.append({
                        'snapshot_id': snapshot.id,
                        'snapshot_time': snapshot.start_datetime.isoformat(),
                        'volume_id': volume_id,
                        'instance_id': instance.id,
                        'original_reason': reason,
                        'reason': 'keep, prune not enabled',
                    })
                elif snapshot.start_datetime > now - timedelta(days=1):
                    kept_snapshots.append({
                        'snapshot_id': snapshot.id,
                        'snapshot_time': snapshot.start_datetime.isoformat(),
                        'volume_id': volume_id,
                        'instance_id': instance.id,
                        'original_reason': reason,
                        'reason': 'keep, not older than one day',
                    })
                else:  # kept is false and no special case
                    pruned_snapshots.append({
                        'snapshot_id': snapshot.id,
                        'snapshot_time': snapshot.start_datetime.isoformat(),
                        'volume_id': volume_id,
                        'instance_id': instance.id,
                        'reason': reason,
                    })
                    if not module.check_mode:  # Keep == false, but in check mode
                        conn.delete_snapshot(snapshot.id)

    module.exit_json(changed=changed, pruned=pruned_snapshots, kept=kept_snapshots)


from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
