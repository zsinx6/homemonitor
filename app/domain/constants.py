# All tunable game numbers in one place.
# Change here and it propagates everywhere.

# EXP gains
EXP_PER_HEALTHY_CYCLE = 1       # all servers UP
EXP_INTERACT = 2                # petting the Digimon
EXP_COMPLETE_TASK = 20          # marking a task done
EXP_BACKUP = 50                 # running a backup

# HP changes
HP_LOSS_PER_DOWN_CYCLE = 2      # any server DOWN each cycle
HP_GAIN_ON_RECOVERY = 1         # a single server returns UP (per recovered server)
HP_GAIN_COMPLETE_TASK = 1       # completing a task
HP_GAIN_BACKUP = 5              # running a backup
HP_DRAIN_BACKUP_OVERDUE = 1     # per cycle when backup is >30 days overdue

# HP bounds
HP_MAX = 10
HP_MIN = 0

# EXP bounds
EXP_MIN = 0

# Level-up
INITIAL_MAX_EXP = 100
LEVEL_UP_SCALE = 1.5            # max_exp multiplier each level

# Status thresholds
HP_HAPPY_THRESHOLD = 7          # hp >= this AND no downs AND interacted recently
HP_SAD_THRESHOLD = 4            # hp >= this (but below happy threshold) OR any server DOWN
# hp <= 3 → injured; hp == 0 → critical

# Interaction / loneliness
LONELINESS_HOURS = 24           # hours without interaction before "lonely" state
HP_DRAIN_LONELY = 1             # HP drained per cycle when pet has not been interacted with
INTERACT_COOLDOWN_SECONDS = 30  # minimum seconds between interactions to prevent EXP farming

# Backup overdue
BACKUP_OVERDUE_DAYS = 30

# Monitoring
MONITOR_INTERVAL_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
PING_TIMEOUT_SECONDS = 3

# Task display cap
COMPLETED_TASKS_DISPLAY_CAP = 20
