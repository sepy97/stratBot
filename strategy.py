import util

class Strategy:
    def __init__(self, name="", type="", patterns=None, tfc=None, exit=None):
        self.name = name
        self.type = type
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

    def export_strategy(self, filename):
        strategies_from_file = util.tomlkit.loads(util.Path(filename).read_text())
        for element in strategies_from_file["strategies"]:
            if element["name"] == self.name:
                print ("Strategy already exists")
                return False
        print ("strategies_from_file: " + str(strategies_from_file))
        strat = {'name': self.name, 'type': self.type, 'patterns': self.patterns, 'tfc': self.tfc, 'exit': self.exit}
        strat_table = util.tomlkit.item(strat)
        strat_table.add(util.tomlkit.nl())
        strategies_from_file['strategies'].append(strat_table)
        util.Path(filename).write_text(util.tomlkit.dumps(strategies_from_file))

    def detect(self, data):
        status = util.TickerStatus.OUT
        for t in self.tfc:
            if data[t][0].get_direction() != self.tfc[t]:
                print("TFC is not the same for ", t)
                print(data[t][0].get_direction(), " should be ", self.tfc[t])
                return None 
        for p in self.patterns:
            candle_kinds = self.patterns[p].split("-")
            for i in range(len(candle_kinds)):
                print("Timeframe: ", p)
                print("Candle ", candle_kinds[i], " comparing to ", data[p][i].to_string())
                if candle_kinds[i] == data[p][i].to_string():
                    print("Match found")
                else:
                    print("No match")
                    return None
        if self.type == "Long":
            status = util.TickerStatus.LONG
        elif self.type == "Short":
            status = util.TickerStatus.SHORT
        else:
            print("Error: strategy type is not Long or Short")
            return None
        return status

    def exit_signal(self, data):
        if self.exit["type"] == "counter-reversal":
            for p in self.exit:
                if p != "type": # ignore the first element which is a description of the type (short/long)
                    print("Exit signal for ", p)
                    print("Candle ", self.exit[p])
                    candle_kinds = self.exit[p].split("-")
                    for i in range(len(candle_kinds)):
                        print("Timeframe: ", p)
                        print("Candle ", candle_kinds[i], " comparing to ", data[p][i].to_string())
                        if candle_kinds[i] == data[p][i].to_string():
                            print("Match found")
                        else:
                            print("No match")
                            return False
        return True
