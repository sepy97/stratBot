import util

class Strategy:
    def __init__(self, name="", type=""):
        self.name = name
        self.type = type
        self.score = 0
        self.weights = {}
        self.penalties = {}
        self.exit_condition = None
        self.threshold = 0
        self.AS = []
        self.status = util.TickerStatus.OUT

    def stratFromDict(self, data):
        self.name = data['name']
        self.type = data['type']
        self.weights = data['weights']
        self.penalties = data['penalties']
        self.exit_condition = data['exit']
        self.threshold = data['threshold']

    def updateTFC(self, data):
    # TODO: implement when TFC is figured out and formalized in .toml file
        if self.type == "Long":
            for tf in (self.weights).keys():
                if data[tf].get_direction() == "G":
                    self.AS[tf] = True
                else:
                    self.AS[tf] = False
        elif self.type == "Short":
            return
        else:
            return

    def checkScore(self, data):
        self.score = 0
        if self.type == "Long":
            for w in self.weights:
                if data[w][0].get_kind() == "2" and data[w][0].get_subtype() == "U":
                    self.score += self.weights[w]
                else:
                    self.score += self.penalties[w]
            if self.score >= self.threshold:
                self.status = util.TickerStatus.LONG
                return self.status
        return self.status