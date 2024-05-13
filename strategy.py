import util

class Strategy:
    def __init__(self, name="", type="", patterns=None, tfc=None, exit=None):
        self.name = name
        self.type = type
        self.AS = []
        if patterns is None:
            self.patterns = {}
        else:
            self.patterns = patterns
        if tfc is None:
            self.tfc = {}
        else:
            self.tfc = tfc
        if exit is None:
            self.exit = {}
        else:
            self.exit = exit

    def updateAS(self, data, timeframes):
        self.AS = [] # reset the list of active signals
        for p in self.patterns:
            # TODO: detect all actionable signals
            self.AS.append("PLACEHOLDER")

    def checkTrigger(self, data):
        # TODO: check for conditions to trigger a signal
        status = util.TickerStatus.LONG
        return status
