Cloudar Automation Tag (CAT) Modules
====================================
These Ansible modules provide a flexible way to manage EC2 instances in AWS. By adding a JSON dictionary in a tag,
instances can be started and stopped, snapshots can be created and old snapshots can be deleted.

A full explanation of why we build this can be found on [the Cloudar blog](http://www.cloudar.be/awsblog/instance-and-snapshot-management-with-ansible) 

Some things to consider:

- The tag should always be valid JSON
- Dates and times are always interpreted as UTC
- JSON dictionaries can be combined. See the full example:


Create snapshot
---------------
Automatically create a snapshot when the playbook is run between TIME and TIME + GRACE PERIOD

### Tag structure
    {
        "sn": TIME
    }

or

    {
        "sn": [
            TIME,
            TIME,
            TIME
        ]
    }
   
Where `TIME` indicates when the action should be triggered.

`TIME` is formatted as 'military time'. So no punctuation and with leading zero. Examples: `"1200"` to trigger at noon,
`"0730"` for half past seven in the morning and `"1700"`  for five o'clock in the evening.

### Usage in a playbook
    - name: Create snapshots
      cat_create_snapshot:
        tag: CAT
        grace: 10

### Examples

When you want a snapshot at 3:30AM CET (2:30AM UTC) every day, the automation tag looks like this:

    {
        "sn": "0230"
    }

If you want a snapshot at noon CET (11AM UTC) and midnight CET (11PM UTC), the tag looks like:

    {
        "sn": [
            "1100",
            "2300"
        ]
    }


Prune snapshot
--------------
Delete old snapshots, but keep x amount of dailies; weeklies (7d), monthlies (30.4375d) and yearlies(365.25d). Snapshots
younger then 1 day will always be kept.

### Tag structure
    {
        "ret": {
             "d": AMOUNT,
             "w": AMOUNT,
             "m": AMOUNT,
             "y": AMOUNT
        }
    }

Where `"d"`, `"w"`, `"m"` and `"y"` stand for daily, weekly, monthly, and yearly respectively. AMOUNT specifies how many
daily, weekly, ... snapshots should be retained. If you don't want a type of snapshots to retain, you can skip the 
letter. If there is no "ret" key in the automation tag, all snapshots will be kept.

### Usage in a playbook
    - name: Prune old snapshots
      cat_prune_snapshot:
        tag: CAT

### Example
Keep 7 daily snapshots, 5 weekly snapshots, 12 monthly snapshots and 6 yearly snapshots:

    {
        "ret": {
             "d": "7",
             "w": "5",
             "m": "12",
             "y": "6"
        }
    }

Start and stop instances
------------------------
Start (or stop) an instance when the current time is between TIME and TIME + GRACE_TIME

### Tag structure
    {
        "on": {
           DAYS: TIME,
           DAYS: TIME 
        },
        "off": {
            DAYS: TIME
        }
    }

Where `DAYS`, and `TIME` indicate when the action should be triggered.

### Usage in a playbook
    - name: start and stop tagged instances
      cat_start_stop:
      tag: CAT
      grace: 10

### Example
Start the instance at 9AM CET (so 8AM UTC) and stop it at 5PM CET (4PM UTC) on weekdays, start at 10AM and stop at 5PM
on Saturday and do nothing on Sunday:

    {
        "on": {
           "12345": "0800",
           "6": "0900" 
        },
        "off": {
            "123456": "1600"
        }
    }


Full Example
------------
Combining all examples:

- Start the instance at 9AM CET (so 8AM UTC) and stop it at 5PM CET (4PM UTC) on weekdays
- Start at 10AM and stop at 5PM on Saturday
- Don't start or stop anything on Sunday
- Take a snapshot at noon CET (11AM UTC)
- Take a snapshot at midnight CET (11PM UTC)
- Keep 7 daily snapshots, 5 weekly snapshots, 12 monthly snapshots and 6 yearly snapshots:

### Tag
    {
        "on": {
           "12345": "0800",
           "6": "0900" 
        },
        "off": {
            "123456": "1600"
        },
        "sn": [
            "1100",
            "2300"
        ],
        "ret": {
             "d": "7",
             "w": "5",
             "m": "12",
             "y": "6"
        }
    }
### Playbook
    ---
    
    - name: start and stop tagged instances
      cat_start_stop:
        tag: CAT
        grace: 10
    - name: Create snapshots
      cat_create_snapshot:
        tag: CAT
        grace: 10
    - name: Prune old snapshots
      cat_prune_snapshot:
        tag: CAT
    