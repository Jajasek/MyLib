from MyLib.shared_data import Shared_data


class Tabulator(Shared_data):
    TABULATOR = "    "

    # noinspection PyAttributeOutsideInit
    def first_init(self, *args, **kwargs):
        self.count = 0


class Log_callable:
    def __init__(self, callable_, file=None):
        self.callable = callable_
        self.tab = Tabulator('_Logging_tabulator_count')

    def __call__(self, *args, **kwargs):
        print(self.tab.count * self.tab.TABULATOR, f"callable: {self.callable} ; {args}, {kwargs}", sep='')
        self.tab.count += 1
        try:
            return self.callable(*args, **kwargs)
        finally:
            self.tab.count -= 1
