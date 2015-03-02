#!/usr/bin/python
from datetime import datetime, timedelta

try:
    import boto.ec2
except ImportError:
    print "failed=True msg='boto required for this module'"
    sys.exit(1)

AUTOMATION_TAG = 'CAT'
GRACE_MINUTES = 10


def main():
    # Output variables
    changed = False
    created_snapshots = []

    # Input
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        tag=dict(required=False, default=AUTOMATION_TAG),
        grace=dict(required=False, default=GRACE_MINUTES, )
    ))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    automation_tag = module.params.get('tag', AUTOMATION_TAG)
    grace_minutes = module.params.get('grace', GRACE_MINUTES)

    # Get all the times of the actions we should trigger
    now = datetime.utcnow()
    times = []
    for minute in range(0, grace_minutes):
        action_time = now - timedelta(minutes=minute)
        times.append(action_time)

    # Get all the snapshots and instances with an automation tag
    conn = ec2_connect(module)
    filters = {
        'tag-key': automation_tag
    }
    instances = conn.get_only_instances(filters=filters)
    snapshots = conn.get_all_snapshots(filters=filters)

    # We use the description to check if a snapshot exists. Make a list for easy access
    snapshot_descriptions = map(lambda x: x.description, snapshots)

    snapshot_configs = {}
    for instance in instances:
        # Get the automation tag (should exists, because we filtered)
        automation = json.loads(instance.tags[automation_tag])

        try:
            snapshot_times = automation['sn']
        except KeyError as e:
            continue

        if not isinstance(snapshot_times, list):
            snapshot_times = [snapshot_times]

        make_snapshot = False
        trigger_datetime = None
        for trigger_time in times:
            for snapshot_time in snapshot_times:
                if '%(h)02d%(m)02d' % {'h': trigger_time.hour, 'm': trigger_time.minute} == snapshot_time:
                    make_snapshot = True
                    trigger_datetime = trigger_time
                    break  # Exit snapshot_times loop
                elif '%(h)d%(m)02d' % {'h': trigger_time.hour, 'm': trigger_time.minute} == snapshot_time:
                    make_snapshot = True
                    trigger_datetime = trigger_time
                    break  # Exit snapshot_times loop
            if make_snapshot:
                break  # Exit times loop

        if not make_snapshot:
            continue  # Try again with the next instance

        for dev, mapping_type in instance.block_device_mapping.items():
            snapshot_config = {
                'instance_id': instance.id,
                'volume_id': mapping_type.volume_id,
                'device': dev,
                'time': trigger_datetime,
            }

            snapshot_configs[mapping_type.volume_id] = snapshot_config

    for volume_id, config in snapshot_configs.items():
        trigger_date_string = config['time'].strftime('%Y-%m-%dT%H:%M')
        instance_id = config['instance_id']
        device = config['device']
        description = 'cat_sn_%(id)s_%(date)s' % {'id': volume_id, 'date': trigger_date_string}

        if description in snapshot_descriptions:
            continue

        snapshot_name = '%(inst)s-%(vol)s-%(date)s' % {
            'inst': instance_id, 'vol': volume_id, 'date': datetime.utcnow().isoformat()
        }

        generated_tag = {'prune': True, 'type': 'default', 'map': {'i': instance_id, 'd': device, 'v': volume_id}}
        if module.check_mode:
            snapshot_id = None
        else:
            snapshot = conn.create_snapshot(volume_id, description=description)
            conn.create_tags(snapshot.id, {
                'Name': snapshot_name,
                automation_tag: json.dumps(generated_tag)
            })
            snapshot_id = snapshot.id

        changed = True
        created_snapshots.append({'snapshot_id': snapshot_id, 'description': description, 'tag': generated_tag})

    module.exit_json(changed=changed, snapshots=created_snapshots)


from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
