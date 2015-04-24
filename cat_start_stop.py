#!/usr/bin/python

DOCUMENTATION = '''
module: cat_start_stop
short_description: Start and stop EC2 instances with an automation tag
description:
  - Start and stop EC2 instances with an automation tag
  - See U(https://cloudar.atlassian.net/wiki/display/AKT/Schedule+starting+and+stopping+instances)
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
- cat_start_stop:
    tag: CAT
    grace: 10
'''

from datetime import datetime, timedelta

try:
    import boto.ec2
except ImportError:
    print "failed=True msg='boto required for this module'"
    sys.exit(1)

AUTOMATION_TAG = 'CAT'
GRACE_MINUTES = 10


def main():
    changed = False
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        tag=dict(required=False, default=AUTOMATION_TAG),
        grace=dict(required=False, default=GRACE_MINUTES, )
    ))

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    automation_tag = module.params.get('tag', AUTOMATION_TAG)
    grace_minutes = module.params.get('grace', GRACE_MINUTES)
    if grace_minutes.isdigit():
        grace_minutes = int(grace_minutes)
    else:
        module.fail_json(msg='"grace" should be an integer value')

    # Get all the times of the actions we should trigger
    now = datetime.utcnow()
    times = []
    for minute in range(0, grace_minutes):
        action_time = now - timedelta(minutes=minute)
        times.append(action_time)

    # Get all the instances with an automation tag
    conn = ec2_connect(module)
    filters = {
        'tag-key': automation_tag
    }
    instances = conn.get_only_instances(filters=filters)

    start_instances = []
    stop_instances = []
    skipped_instances = []
    for instance in instances:
        skipped = None

        # Get the automation tag (should exists, because we filtered)
        automation = json.loads(instance.tags[automation_tag])

        try:
            for days, trigger_time in automation['on'].items():
                for action_time in times:
                    if str(action_time.weekday() + 1) not in days:
                        skipped = {'id': instance.id, 'reason': 'No on trigger for this day'}
                    elif '%(h)02d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                        start_instances.append(instance)
                        skipped = False
                    elif '%(h)d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                        start_instances.append(instance)
                        skipped = False
        except KeyError:
            skipped = {'id': instance.id, 'reason': 'No on key'}

        try:
            for days, trigger_time in automation['off'].items():
                for action_time in times:
                    if str(action_time.weekday() + 1) not in days:
                        if skipped is None:
                            skipped = {'id': instance.id, 'reason': 'No off trigger for this day'}
                    elif '%(h)02d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                        if instance.state != 'stopped':
                            stop_instances.append(instance)
                            skipped = False
                    elif '%(h)d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                        stop_instances.append(instance)
                        skipped = False
        except KeyError:
            skipped = {'id': instance.id, 'reason': 'No off key'}

        if skipped:
            skipped_instances.append(skipped)

    stop_ids = []
    start_ids = []
    if stop_instances:  # not empty
        for instance in stop_instances:
            if instance.state != 'stopped':
                changed = True
                stop_ids.append(instance.id)
    if start_instances:  # not empty
        for instance in start_instances:
            if instance.state != 'running':
                changed = True
                start_ids.append(instance.id)

    if stop_ids and not module.check_mode:
        conn.stop_instances(stop_ids)
    if start_ids and not module.check_mode:
        conn.start_instances(start_ids)

    module.exit_json(changed=changed, started=start_ids, stopped=stop_ids, skipped_instances=skipped_instances)


from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
