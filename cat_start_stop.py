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
    changed = False
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        tag=dict(required=False, default=AUTOMATION_TAG),
        grace=dict(required=False, default=GRACE_MINUTES, )
    ))

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)

    automation_tag = module.params.get('tag', AUTOMATION_TAG)
    grace_minutes = module.params.get('grace_minutes', GRACE_MINUTES)

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
    for instance in instances:
        # Get the automation tag (should exists, because we filtered)
        automation = json.loads(instance.tags[automation_tag])

        for days, trigger_time in automation['on'].items():
            for action_time in times:
                if str(action_time.weekday() + 1) not in days:
                    pass
                elif '%(h)02d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                    start_instances.append(instance)
                elif '%(h)d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                    start_instances.append(instance)
        for days, trigger_time in automation['off'].items():
            for action_time in times:
                if str(action_time.weekday() + 1) not in days:
                    pass
                elif '%(h)02d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                    if instance.state != 'stopped':
                        stop_instances.append(instance)
                elif '%(h)d%(m)02d' % {'h': action_time.hour, 'm': action_time.minute} == trigger_time:
                    stop_instances.append(instance)

    stop_ids = []
    start_ids = []
    if stop_instances:  # not empty
        for instance in stop_instances:
            if instance.state != 'stopped':
                changed = True
                stop_ids.append(instance.id)
        if not module.check_mode:
            conn.stop_instances(stop_ids)
    if start_instances:  # not empty
        for instance in start_instances:
            if instance.state != 'running':
                changed = True
                start_ids.append(instance.id)
        if not module.check_mode:
            conn.start_instances(start_ids)

    module.exit_json(changed=changed, started=start_ids, stopped=stop_ids)


from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
