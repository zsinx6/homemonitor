# All tunable game numbers in one place.
# Change here and it propagates everywhere.

# EXP gains
EXP_PER_HEALTHY_CYCLE = 1       # all servers UP
EXP_INTERACT = 2                # petting the Digimon
EXP_COMPLETE_TASK = 20          # marking a task done
EXP_BACKUP = 30                 # running a backup

# HP changes
HP_LOSS_PER_DOWN_CYCLE = 1      # HP lost *per downed server* each cycle (scales with count)
HP_GAIN_ON_RECOVERY = 1         # a single server returns UP (per recovered server)
HP_GAIN_INTERACT = 1            # petting the Digimon
HP_GAIN_COMPLETE_TASK = 1       # completing a task
HP_GAIN_BACKUP = 5              # running a backup
HP_DRAIN_BACKUP_OVERDUE = 1     # per cycle when backup is >30 days overdue

# HP bounds
HP_MAX = 10
HP_MIN = 0
HP_REVIVE = 7                   # HP restored on revival — matches HP_HAPPY_THRESHOLD so the pet isn't permanently sad after revival

# EXP bounds
EXP_MIN = 0

# Level-up
INITIAL_MAX_EXP = 100
LEVEL_UP_SCALE = 1.5            # max_exp multiplier each level

# Status thresholds
HP_HAPPY_THRESHOLD = 7          # hp >= this AND no downs AND interacted recently
# hp <= 3 → injured; hp == 0 → critical

# Interaction / loneliness
LONELINESS_HOURS = 24           # hours without interaction before "lonely" state
HP_DRAIN_LONELY = 1             # HP drained per cycle when pet has not been interacted with
INTERACT_COOLDOWN_SECONDS = 30  # minimum seconds between interactions to prevent EXP farming

# Backup cooldown
BACKUP_COOLDOWN_HOURS = 1       # minimum hours between backup rewards

# Backup overdue
BACKUP_OVERDUE_DAYS = 30

# Digital Dust (V3)
MAX_DUST = 5
DUST_SPAWN_HOURS = 5                # dust spawns at most once per 5 hours
DUST_HP_DRAIN_CYCLE_MODULO = 3     # drain -1 HP every 3 cycles at max dust
EXP_CLEAN_REWARD = 2                # EXP granted when cleaning dust
HP_DRAIN_MAX_DUST = 1               # HP lost per drain event at max dust

# Daily Mood (V3)
MOODS = ["Energetic", "Melancholy", "Rebellious", "Philosophical", "Anxious", "Zen"]

# Pomodoro Focus (V3)
FOCUS_COOLDOWN_MINUTES = 30
EXP_FOCUS_REWARD = 15
HP_FOCUS_REWARD = 2
MONITOR_INTERVAL_SECONDS = 600
MONITOR_CYCLE_TIMEOUT_SECONDS = 120   # abort if a cycle takes longer than this
HTTP_TIMEOUT_SECONDS = 10
PING_TIMEOUT_SECONDS = 3
TCP_TIMEOUT_SECONDS = 5

# Task display cap
COMPLETED_TASKS_DISPLAY_CAP = 20

# ---------------------------------------------------------------------------
# Evolution tiers — original Digimon line created for this app
#
# To add a new tier (e.g. Ultra after perfect):
#   1. Add a dict entry here BEFORE the last entry, keeping min_level sequential.
#   2. Add matching face art in static/index.html → STAGE_FACES[stage].
#   3. Run pytest to verify nothing broke.
# ---------------------------------------------------------------------------
EVOLUTION_TIERS = [
    {"min_level": 1,  "max_level": 1,    "species": "Bitmon",    "stage": "fresh"},
    {"min_level": 2,  "max_level": 4,    "species": "Nibblemon", "stage": "in-training"},
    {"min_level": 5,  "max_level": 14,   "species": "Packamon",  "stage": "rookie"},
    {"min_level": 15, "max_level": 29,   "species": "Hostimon",  "stage": "champion"},
    {"min_level": 30, "max_level": 9999, "species": "Kernelmon", "stage": "perfect"},
]
