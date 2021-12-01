"""
This module provides framework used to quickly create a small robust
shell-like application with minimal effort.

USAGE:
Application is a subclass of command.App. To create each command, define
a method and decorate it with @Command(syntax). Supported syntax will maybe
grow with time and need. For each user input, the commands are evaluated in
the order of definition and only the first matching will be executed.

Run the application by calling the class.

Each handler (decorated method) will receive the application instance as
the first argument, then any user arguments that carry information.
That is, the first value (the command) will be passed, only if it has free
option. If it has only hard-coded options, those are considered aliases and
the user-typed string is not passed. However, any additional arguments and
options are passed.

To indicate that an user argument is in some way invalid (for example, cannot
be converted to an int), raise command.InvalidArgValue exception with the
invalid value as its argument (and an optional reason). If it is the free
command, use command.InvalidCommandValue exception instead. If the possible
values of the arguments depend on the values of previous arguments and the
dependency rules are violated (For example, consider the command
'greet once|n-times [<n>]'. If option 'n-times' is chosen, [<n>] becomes
mandatory.), raise command.InvalidSyntax exception with the first invalid
value as its argument.

Class App automatically creates commands 'e|exit' and 'h|help' and appends them
at the end of the command list. To change the syntax and/or position on the
list, use the keyword arguments of the __init__ method. To disable automatic
creation of these commands, pass an empty string as the syntax.

The help message is generated from the docstrings of the handler functions.

SUPPORTED SYNTAX:
syntax is a string, that consists of any number of parts delimited by spaces.
First part serves as the command name.
[opt1|opt2|<free-option>]
Empty syntax matches only empty command.

AUTHOR:
Jáchym Mierva, https://github.com/Jajasek

LICENCE:
GNU General Public License, version 2
"""

# Ideas for future extension:
#  - use the distance.levenshtein metric to better find typos and sort error
#    messages
#  - use modular approach to parsing arguments

from __future__ import annotations  # Piping instead of Union

from typing import Callable, Sequence
import sys


HELP_WIDTH: int = 78
MAX_HELP_INDENT: int = 25
_INITIAL_BADNESS: int = 10000


class _ParsingError(Exception):
    """Exception used to indicatie that parsing of a particular command part
    has failed.
    """

    def __init__(self, message: str, badness: int) -> None:
        super().__init__()
        self.message = message
        self.badness = badness


class _InvalidOption(_ParsingError):
    """Part is mandatory and user argument is not any of the options."""

    def __init__(self, part: _Part, value: str) -> None:
        super().__init__(f"Invalid option '{value}', must be one of '{part}'",
                         3)
        self.part = part
        self.value = value


class _MissingMandatory(_ParsingError):
    """User arguments were exhausted and haven't filled all mandatory parts."""

    def __init__(self, part: _Part) -> None:
        super().__init__(f"Missing mandatory argument '{part}'", 4)
        self.part = part


class _Redundant(_ParsingError):
    """All parseable parts were filled and there remains an unused user
    argument.
    """

    def __init__(self, value: str) -> None:
        super().__init__(f"Redundant argument '{value}'", 4)
        self.value = value


class InvalidSyntax(_ParsingError):
    """The optionality of a part is variable and was violated."""

    def __init__(self, argument: _Argument, reason: str = ''):
        super().__init__(f"Invalid syntax at '{argument}'"
                         f"{': ' if reason else ''}{reason}", 4)


class InvalidArgValue(_ParsingError):
    """User argument was parsed as a free option, but had an invalid value."""

    def __init__(self, argument: _Argument, reason: str = ''):
        super().__init__(f"Invalid value '{argument}' of argument "
                         f"'{argument.name}'{': ' if reason else ''}{reason}",
                         1)
        self.argument = argument
        self.reason = reason


class InvalidCommandValue(_ParsingError):
    """First part of a command is free, but was given an invalid value."""

    def __init__(self, command: _Argument, reason: str = ''):
        super().__init__(f"Invalid value '{command}' of command "
                         f"'{command.name}'{': ' if reason else ''}{reason}",
                         2)
        self.command = command
        self.reason = reason


class _Argument(str):
    """Mostly normal string, but with added attribute refering to the name of
    the attribute.
    """

    name: str | None

    def __new__(cls, value: str = '', name: str | None = None):
        new = super().__new__(_Argument, value)
        object.__setattr__(new, 'name', name)
        return new


class _Part:
    """Single parameter delimited by spaces. It is either optional (enclosed in
    [OPTION]) or mandatory (otherwise). There can be several hard-coded options
    delimited by '|', and there can be (logically at most one) free option,
    enclosed in <NAME>.
    """

    def __init__(self, part: str) -> None:
        self._str: str = part
        self.mandatory: bool = not self._enclosed(part, '[]')
        if not self.mandatory:
            # strip the brackets
            part = part[1:-1]
        # self.free_name is set to the name inside the <> in next line if at
        # least one of the options is free.
        self.free_name: str = ''
        # hard-coded options
        self.options: list[str] = [
            option for option in part.split('|')
            if not self._enclosed(option, '<>') or not self.free_name and
            setattr(self, 'free_name', option[1:-1])
        ]

    def __repr__(self) -> str:
        return self._str

    def __len__(self) -> int:
        return len(self._str)

    @staticmethod
    def _enclosed(string: str, enclose: str) -> bool:
        """Return True if first and last characters of string are the first and
        second characers of enclose, respectively.
        """
        return string and string[0] == enclose[0] and string[-1] == enclose[1]

    def match(self, user_part: str) -> _Argument:
        """Return the string that is used as argument to the handler if
        parseable, else raise _InvalidOption error.
        """
        if user_part in self.options:
            return _Argument(user_part)
        if self.free_name and user_part:
            return _Argument(user_part, self.free_name)
        if not self.mandatory:
            # it has only hard-coded options and none of them was selected
            return _Argument()
        raise _InvalidOption(self, user_part)


class _Wrapper:
    """The object that is called when handling (or trying to handle) a user
    command.
    """

    def __init__(self, descriptor: _Descriptor, instance, owner) -> None:
        # _Wrapper is created when the _Descriptor is being used on a class or
        # an instance. It inherits all (previously known) information from
        # the descriptor, the only new information is instance and owner,
        # which is used to recover the bound method out of descriptor.handler.

        self._command: _Part = descriptor.command
        self._args: tuple[_Part] = descriptor.args
        # noinspection PyUnresolvedReferences
        self._handler = descriptor.handler.__get__(instance, owner)
        self._syntax: str = descriptor.syntax
        self._description: str = descriptor.description
        self._position: int = descriptor.position
        self._ignore: bool = descriptor.ignore

        # tab is the tabulator position, that is later assigned by CommandList
        # in the context of all command wrappers
        self._tab: int | None = None

        # attributes used during command matching to report exceptions
        self._first_exception: _ParsingError | None = None
        self._badness: int = _INITIAL_BADNESS

    def __repr__(self) -> str:
        return self._syntax

    def __str__(self) -> str:
        return '\n'.join(self._str_lines())

    def _str_lines(self, indent: int = 0) -> list[str]:
        """Create the help entry as a list of lines to allow for indentation.
        """
        if self._tab is None:
            self._tab = len(self._syntax) + 4

        lines: list[str]
        if not self._syntax:
            self._tab = 0
            self._description = ('no command is given, ' + self._description
                                 + '.')
            lines = ['If']
        elif self._tab >= len(self._syntax) + 2:
            # the description can be squished to the syntax, as long as there
            # are at least 2 spaces left
            lines = [self._syntax + ' ' * (self._tab - len(self._syntax) - 1)]
        else:
            # otherwise the description will begin on the next line
            lines = [self._syntax, ' ' * (self._tab - 1)]

        # Prevent the creation of a blank line if the first word is (somehow)
        # too long to fit. In that case, it will be
        # printed anyway.
        not_first_word: bool = False
        for word in self._description.split():
            if (len(lines[-1]) + len(word) >= HELP_WIDTH - indent
                    and not_first_word):
                lines.append(' ' * self._tab + word)
            else:
                lines[-1] += ' ' + word
            not_first_word = True
        return lines

    def indent(self, spaces: int = 4) -> str:
        """same as __str__, but add specified number of spaces at the beginning
        of each line.
        """
        indent: str = ' ' * spaces
        return indent + ('\n' + indent).join(self._str_lines())

    def __call__(self, user_command: str, *user_args: str) -> bool:
        """Try to parse user input and run the handler in case of success. If
        the first part (command) doesn't match, return False. If later parts
        don't match, calculate the badness and throw a _ParsingError. If it
        matches and runs smoothly, return True.
        """
        self._first_exception = None

        # if not user_command and self._command.mandatory:
        #     return False
        try:
            resolved_command: str = self._command.match(user_command)
        except _ParsingError:
            return False

        # if the command carries information, it will be the first argument
        resolved_args: list[str] = (
            [resolved_command] if self._command.free_name or
            not self._command.mandatory else [])
        if user_command in self._command.options:
            # user typed one of the hardcoded options, so it was probably his
            # intention
            self._badness -= 3

        # the for-loop iterates over the parts of the syntax, but we need to
        # iterate over the parts of user_args asynchronously
        user_arg: str | None = None
        user_args_index: int = 0
        for part in self._args:
            if user_arg is None and user_args_index < len(user_args):
                # we have matched the previous user_arg
                user_arg = user_args[user_args_index]
                user_args_index += 1
            if user_arg is None and part.mandatory:
                self._log_exception(_MissingMandatory(part))
                break
            try:
                resolved_args.append(part.match(user_arg or ''))
            except _ParsingError as e:
                # suppose it is a typo and pretend a match
                self._log_exception(e)
                user_arg = None
                continue
            if resolved_args[-1]:
                # we have matched, the part wasn't skipped as optional
                user_arg = None
                # more matches mean this was more probably user's intention
                self._badness -= 1
        if user_arg is not None:
            self._log_exception(_Redundant(user_arg))
        elif user_args_index < len(user_args):
            self._log_exception(_Redundant(user_args[user_args_index]))

        if not self._first_exception:
            # The user input matched, try to run the handler.
            try:
                self._handler(*resolved_args)
            except _ParsingError as e:
                self._log_exception(e)

        if self._first_exception:
            self._first_exception.badness += self._badness
            raise self._first_exception

        return True

    def _log_exception(self, exception: _ParsingError) -> None:
        """Save the first exception, but update badness with more exceptions.
        The overall badness is the highest badness of all exceptions.
        """
        if not self._first_exception:
            self._first_exception = exception
        else:
            self._first_exception.badness = max(self._first_exception.badness,
                                                exception.badness)

    def call(self, *args, **kwargs) -> None:
        """Direct call without parsing."""
        self._handler(*args, **kwargs)


class _Descriptor:
    """The class that gets stored instead of the handler function. When it is
    retrieved using __get__, it will create the callable _Wrapper object.
    """

    def __init__(self, command: Command, handler: Callable[..., None]) -> None:
        # the syntax information is inherited from the Command
        self.command: _Part = command.command
        self.args: tuple[_Part] = command.args
        self.syntax: str = str(command)
        self.position: int = command.position
        self.ignore: bool = command.ignore

        self.handler = handler
        self.description: str = handler.__doc__ or 'description not available'
        self.description = self.description.replace('\n', ' ')

    def __repr__(self) -> str:
        return self.syntax

    def __get__(self, instance, owner) -> _Wrapper:
        return _Wrapper(self, instance, owner)


class CommandListD(tuple[_Descriptor]):
    """Immutable ordered collection of command descriptors. If it is retrieved
    using __get__, it will cast all descriptors to wrappers.
    """

    def __new__(cls, *values: _Descriptor) -> CommandListD:
        # find the command with the longest syntax and set the tabulator
        # position accordingly
        largest_tab = 0
        for descriptor in values:
            # if the resulting tabulator value would be too large, skip the
            # descriptor; it will print the syntax on a separate line
            if len(descriptor.syntax) + 4 <= MAX_HELP_INDENT:
                largest_tab = max(largest_tab, len(descriptor.syntax) + 4)

        for descriptor in values:
            descriptor.tab = largest_tab
        return super().__new__(cls, values)

    def __get__(self, instance, owner) -> tuple[_Wrapper]:
        def cast(descriptor: _Descriptor) -> _Wrapper:
            return descriptor.__get__(instance, owner)
        return tuple(cast(descriptor) for descriptor in self)


class CommandList(tuple[_Wrapper]):
    """Immutable ordered collection of command wrappers. At the time of
    creation it finds the tabulator position.
    """

    # noinspection PyProtectedMember
    def __new__(cls, *values: _Wrapper) -> CommandList:
        # find the command with the longest syntax and set the tabulator
        # position accordingly
        largest_tab = 0
        for wrapper in values:
            # if the resulting tabulator value would be too large, skip the
            # descriptor; it will print the syntax on a separate line
            if len(wrapper._syntax) + 4 <= MAX_HELP_INDENT:
                largest_tab = max(largest_tab, len(wrapper._syntax) + 4)

        for wrapper in values:
            wrapper._tab = largest_tab
        return super().__new__(cls, values)


class Command:
    """The decorator class used to mark a method as a command handler and
    define its syntax. To exclude a command from the command list, set
    the keyword argument 'ignore' to True.
    """
    next_position: int = 0

    def __init__(self, syntax: str, /, ignore: bool = False) -> None:
        try:
            command, *args = syntax.split()
        except ValueError:
            command = ''
            args = tuple()
        self.command: _Part = _Part(command)
        self.args: tuple[_Part] = tuple(_Part(arg) for arg in args)
        self._str: str = (str(self.command)
                          + ''.join(f' {arg}' for arg in self.args))
        self.position: int = self.__class__.next_position
        self.__class__.next_position += 1
        self.ignore = ignore

    def __call__(self, handler: Callable[..., None]) -> _Descriptor:
        return _Descriptor(self, handler)

    def __repr__(self) -> str:
        return self._str

    def __len__(self) -> int:
        return len(self._str)


# noinspection PyMethodParameters
class App:
    """Simple class to further facilitate the app creation."""

    def __init__(self, /, s_exit: str = 'e|exit', p_exit: int = sys.maxsize,
                 s_help: str = 'h|help', p_help: int = sys.maxsize) \
            -> None:
        self.running: bool = False

        def insert_cmd(handler: Callable, syntax: str, position: int) -> None:
            if syntax:
                lst.insert(position, Command(syntax)(handler).__get__(
                    self, self.__class__))

        # noinspection PyProtectedMember
        lst: list[_Wrapper] = sorted(
            [entry for entry_str in dir(self) if
             isinstance(entry := getattr(self, entry_str), _Wrapper) and
             not entry._ignore],
            key=lambda w: w._position
        )
        if p_exit >= p_help:
            insert_cmd(_help, s_help, p_help)
            insert_cmd(_exit, s_exit, p_exit)
        else:
            insert_cmd(_exit, s_exit, p_exit)
            insert_cmd(_help, s_help, p_help)
        self.command_list: CommandList = CommandList(*lst)
        self.main()

    def main(self):
        self.running = True
        while self.running:
            resolve(self.command_list, input('>>> '))


# noinspection PyPep8Naming
class resolve:
    """Emulated function. Find a command in command_list that matches the
    user_input and run it. If none is found, print parsing errors that occured
    and try to find a help command, execute it if it exists.
    """

    _help_search: bool = False

    def __new__(cls, command_list: Sequence[_Wrapper],
                user_input: str) -> None:
        user_list: list[str] = user_input.split() or ['']
        logged_exceptions: list[_ParsingError] = []
        for command_wrapper in command_list:
            try:
                if command_wrapper(*user_list):
                    return
            except _ParsingError as e:
                logged_exceptions.append(e)
        if logged_exceptions:
            if cls._help_search:
                # this is second, recursed run to find help command
                print('No additional help found.')
            else:
                # the user_input was really user input: tell him what is wrong
                cls._print_exceptions(logged_exceptions)
                cls._help_search = True
                resolve(command_list, 'help')
                cls._help_search = False
            return
        # no exception has occured, but also no command matched the user_input.
        if cls._help_search:
            print('No additional help found.')
            return
        if user_list[0]:
            print(f'Unknown command {user_list[0]}.')
            print()
        cls._help_search = True
        resolve(command_list, 'help')
        cls._help_search = False

    @classmethod
    def _print_exceptions(cls, exceptions: list[_ParsingError]):
        # print most likely mistakes first
        exceptions.sort(key=lambda err: err.badness)

        # remove duplicities
        messages: set[str] = set()
        to_print: list[int] = []
        for i, e in enumerate(exceptions):
            if e.message not in messages:
                messages.add(e.message)
                to_print.append(i)

        if len(to_print) > 1:
            print('    ', end='')
        print('\nor  '.join(exceptions[i].message for i in to_print),
              end='.\n\n')


def _exit(self):
    """exit the program"""
    self.running = False


def _help(self):
    """show this help"""
    print('Available commands:')
    no_command: _Wrapper | None = None
    for wrapper in self.command_list:
        if repr(wrapper):
            print(wrapper.indent(2))
        else:
            no_command = wrapper
    if no_command is not None:
        print(no_command)


__all__ = ['Command', 'App', 'CommandList', 'resolve', 'InvalidSyntax',
           'InvalidCommandValue', 'InvalidArgValue']
