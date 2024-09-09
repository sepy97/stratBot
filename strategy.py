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
        self.inForce = []
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
    # In Force means AS triggered. TODO: how to deal with AS that triggered and failed? 
    def inForce(self, candles):
        #   Long: 1-2u, 2d-2u 
        if self.type == "Long":
            for tf in (self.weights).keys():
                if candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "U" and \
                    (candles[tf][1].get_kind() == "1" or (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "D")):
                    self.inForce[tf] = True
                else:
                    self.inForce[tf] = False
        #   Short: 1-2d, 2u-2d
        else:
            for tf in (self.weights).keys():
                if candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "D" and \
                    (candles[tf][1].get_kind() == "1" or (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "U")):
                    self.inForce[tf] = True
                else:
                    self.inForce[tf] = False


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