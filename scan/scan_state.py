from enum import Enum, auto


class ScanState(Enum):
    IDLE = auto()
    MOVING = auto()
    WAITING_FOR_POSITION = auto()
    SETTLING = auto()
    ACQUIRING = auto()
    SAVING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()
    COMPLETED = auto()
    ERROR = auto()

