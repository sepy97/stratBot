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

    def detect(self, data, ticker_logger):
        status = util.TickerStatus.OUT
        for t in self.tfc:
            if data[t][0].get_direction() != self.tfc[t]:
                ticker_logger.logger.debug("TFC is not the same for " + t + "; " + data[t][0].get_direction() + " should be " + self.tfc[t])
                return None
        for p in self.patterns:
            candle_kinds = self.patterns[p].split("-")
            # Candle kinds in the strategy pattern are kept in chronological order (from the oldest to the newest),
            # while data is stored in reversed order (first the most recent, then the older one, etc)
            #for i in range(len(candle_kinds)):
            n = len(candle_kinds)
            for i in reversed(range(n)):    # start checking from the oldest candle
                ticker_logger.logger.debug("Candle kind # " + str(i) + ": " + candle_kinds[n-i-1] + " vs " + data[p][i].to_string())
                if candle_kinds[n-i-1] != data[p][i].to_string():
                    ticker_logger.logger.debug("No entry match on timeframe " + p)
                    return None
        if self.type == "Long":
            status = util.TickerStatus.LONG
            ticker_logger.logger.info("Long signal detected on strategy " + self.name)
        elif self.type == "Short":
            status = util.TickerStatus.SHORT
            ticker_logger.logger.info("Short signal detected on strategy " + self.name)
        else:
            print("Error: strategy type is not Long or Short")
            return None
        return status

    def exit_signal(self, data, exit_logger):
        if self.exit["type"] == "counter-reversal":
            exit_logger.logger.debug("Exit type is counter-reversal")
            for p in self.exit: # There is only one exit-pattern
                if p != "type": # ignore the first element which is a description of the exit type (e,g, counter-reversal)
                    candle_kinds = self.exit[p].split("-")
                    # Candle kinds in the strategy pattern are kept in chronological order (from the oldest to the newest),
                    # while data is stored in reversed order (first the most recent, then the older one, etc)
                    #for i in range(len(candle_kinds)):
                    for i in reversed(range(len(candle_kinds))):
                        exit_logger.logger.debug("Candle kind # " + str(i) + ": " + candle_kinds[i] + " vs " + data[p][i].to_string())
                        if candle_kinds[i] != data[p][i].to_string():
                            exit_logger.logger.debug("No exit match on timeframe " + p)
                            return False
                    exit_logger.logger.info("Exit signal detected on pattern " + p + ": " + self.exit[p])
        return True
