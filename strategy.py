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
        highTF = self.weights[1:]
        lowTF = self.weights[0]
        #   Long: 1-2u, 2d-2u, 3G (long candle)
        if self.type == "Long":
            for tf in highTF.keys():
                if not (candles[tf][0].close > candles[tf][1].high):
                    self.inForce[tf] = False
                    return
            for tf in lowTF.keys():
                if candles[tf][0].get_direction() == "G" and \
                   (candles[tf][0].close > candles[tf][1].high) and \
                   (candles[tf][0].get_kind() == "3" or \
                   (candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "U" and \
                   (candles[tf][1].get_kind() == "1" or \
                   (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "D")))):
                    self.inForce[tf] = True
                else:
                    self.inForce[tf] = False
        #   Short: 1-2d, 2u-2d, 3R (short candle)
        else:
            for tf in highTF.keys():
                if not (candles[tf][0].close < candles[tf][1].low):
                    self.inForce[tf] = False
                    return
            for tf in lowTF.keys():
                if candles[tf][0].get_direction() == "R" and \
                  (candles[tf][0].close < candles[tf][1].low) and \
                  (candles[tf][0].get_kind() == "3" or \
                  (candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "D" and \
                  (candles[tf][1].get_kind() == "1" or \
                  (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "U")))):
                    self.inForce[tf] = True
                else:
                    self.inForce[tf] = False


    def checkScore(self, data):
        self.score = 0
        if self.type == "Long":
            highTF = self.weights[1:]
            lowTF = self.weights[0]
            # For high timeframes we check if current price is > than previous high
            # Also green TFC (all candles are green)
            for w in self.weights:
                if data[w][0].get_kind() == "2" and data[w][0].get_subtype() == "U":
                    self.score += self.weights[w]
                else:
                    self.score += self.penalties[w]
            if self.score >= self.threshold:
                self.status = util.TickerStatus.LONG
                return self.status

            # On the low timeframe, check inForce
        return self.status

    def isValidEntry(self, candles):
    # On all timeframes we check if current price is > than previous high
        if self.type == "Long":
            for tf in self.weights.keys():
                if not (candles[tf][0].close > candles[tf][1].high):
                    print(f"Current price {candles[tf][0].close} is not > than previous high {candles[tf][1].high}")
                    return False
        else: # Short
            for tf in self.weights.keys():
                if not (candles[tf][0].close < candles[tf][1].low):
                    print(f"Current price {candles[tf][0].close} is not < than previous low {candles[tf][1].low}")
                    return False
        print("@@@ VALID entry: current price is > than previous high on all timeframes")
        return True

    def checkTFC (self, candles):
        if self.type == "Long":
            # Green TFC (all candles are green)
            for tf in self.weights.keys():
                if candles[tf].get_direction() == "R":
                    print(f"TF {tf} is red in a long strategy; all candles should be green!")
                    return False
            print("@@@ All timeframes are GREEN in a long strategy")
            return True
        else: # Short
            # Red TFC (all candles are red)
            for tf in self.weights.keys():
                if candles[tf].get_direction() == "G":
                    print(f"TF {tf} is green in a short strategy; all candles should be red!")
                    return False
            print("@@@ All timeframes are RED in a short strategy")
            return True

    def checkTurnaround(self, candles, tf):
        if self.type == "Long":
            for tf in tf.keys():
                print(f"Timeframe {tf} has ")
                print(f"{candles[tf][0].get_kind()}{candles[tf][0].get_subtype()} {candles[tf][1].get_kind()}{candles[tf][1].get_subtype()}")
                if (candles[tf][0].get_kind() == "3" or \
                   (candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "U" and \
                   (candles[tf][1].get_kind() == "1" or \
                   (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "D")))):
                    print(f"@@@ Timeframe {tf} has a VALID turnaround")
                    return True
        else: # Short
            for tf in tf.keys():
                if (candles[tf][0].get_kind() == "3" or \
                   (candles[tf][0].get_kind() == "2" and candles[tf][0].get_subtype() == "D" and \
                   (candles[tf][1].get_kind() == "1" or \
                   (candles[tf][1].get_kind() == "2" and candles[tf][1].get_subtype() != "U")))):
                    print(f"@@@ Timeframe {tf} has a VALID turnaround")
                    return True
        return False

    def checkSignal(self, candles):
        TFkeys = list(self.weights.keys())
        
        lowestTF = TFkeys[:1]
        return self.isValidEntry(candles) and self.checkTurnaround(candles, lowestTF)
