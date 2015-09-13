#!/usr/bin/env python

import asyncio
import serial
import sys
import pyee
import glob
import logging
import pyee
import copy
import sys
import codecs

DGT_SEND_RESET = 0x40
DGT_SEND_BRD = 0x42
DGT_SEND_UPDATE_BRD = 0x44
DGT_SEND_UPDATE_NICE = 0x4b
DGT_RETURN_SERIALNR = 0x45
DGT_SEND_VERSION = 0x4D

DGT_FONE = 0x00
DGT_BOARD_DUMP = 0x06
DGT_BWTIME = 0x0D
DGT_FIELD_UPDATE = 0x0E
DGT_EE_MOVES = 0x0F
DGT_BUSADRES = 0x10
DGT_SERIALNR = 0x11
DGT_TRADEMARK = 0x12
DGT_VERSION = 0x13
DGT_BOARD_DUMP_50B = 0x14
DGT_BOARD_DUMP_50W = 0x15
DGT_BATTERY_STATUS = 0x20
DGT_LONG_SERIALNR = 0x22

MESSAGE_BIT = 0x80

DGT_CLOCK_MESSAGE = 0x2b

DGT_CMD_CLOCK_BEEP = 0x0b

PIECE_TO_CHAR = {
    0x01: "P",
    0x02: "R",
    0x03: "N",
    0x04: "B",
    0x05: "K",
    0x06: "Q",
    0x07: "p",
    0x08: "r",
    0x09: "n",
    0x0a: "b",
    0x0b: "k",
    0x0c: "q",
}

LOGGER = logging.getLogger(__name__)


class Board(object):

    def __init__(self):
        self.state = bytearray(0x00 for _ in range(64))

    def board_fen(self):
        fen = []
        empty = 0

        for index, c in enumerate(self.state):
            if not c:
                empty += 1

            if empty > 0 and (c or (index + 1) % 8 == 0):
                fen.append(str(empty))
                empty = 0

            if c:
                fen.append(PIECE_TO_CHAR[c])

            if (index + 1) % 8 == 0 and index < 63:
                fen.append("/")

        return "".join(fen)

    def clear(self):
        self.state = bytearray(0x00 for _ in range(64))

    def copy(self):
        return copy.deepcopy(self)


class Connection(pyee.EventEmitter):

    def __init__(self, port_globs, loop):
        super().__init__()

        self.port_globs = list(port_globs)
        self.loop = loop

        # Connection state.
        self.serial = None
        self.board = Board()
        self.message_id = 0
        self.message_buffer = b""
        self.remaining_message_length = 0

    def port_candidates(self):
        for port_glob in self.port_globs:
            yield from glob.iglob(port_glob)

    def connect(self):
        for port in self.port_candidates():
            self.connect_port(port)
            break

    def connect_port(self, port):
        self.close()

        self.serial = serial.Serial(port,
            stopbits=serial.STOPBITS_ONE,
            parity=serial.PARITY_NONE,
            bytesize=serial.EIGHTBITS)

        LOGGER.info("Connected to %s", port)
        self.emit("connected", port)

        self.loop.add_reader(self.serial, self.can_read)

        # Request initial board state and updates.
        self.serial.write(bytearray([DGT_SEND_UPDATE_NICE]))
        self.serial.write(bytearray([DGT_SEND_BRD]))

        self.clock_beep()

    def close(self):
        if self.serial is None:
            return

        self.loop.remove_reader(self.serial)
        self.serial.close()

        LOGGER.info("Disconnected")

        self.serial = None
        self.board.clear()
        self.message_id = 0
        self.message_buffer = b""
        self.remaining_message_length = 0

        self.emit("disconnected")

    def can_read(self):
        try:
            if not self.remaining_message_length:
                # Start of a new message.
                header = self.serial.read(3)
                self.message_id = header[0]
                self.remaining_message_length = (header[1] << 7) + header[2] - 3

            # Read remaining part of the current message.
            message = self.serial.read(self.remaining_message_length)
            self.remaining_message_length -= len(message)
            self.message_buffer += message
        except (TypeError, serial.SerialException):
            self.close()
        else:
            # Full message received.
            if not self.remaining_message_length:
                self.process_message(self.message_id, self.message_buffer)
                self.message_buffer = b""

    def process_message(self, message_id, message):
        LOGGER.debug("Message %s: %s", hex(message_id), codecs.encode(message, "hex"))

        if message_id == MESSAGE_BIT | DGT_BOARD_DUMP:
            self.board.state = bytearray(message)
            self.emit("board", self.board.copy())
        elif message_id == MESSAGE_BIT | DGT_FIELD_UPDATE:
            self.board.state[message[0]] = message[1]
            self.emit("board", self.board.copy())

    def clock_beep(self, ms=100):
        #self.serial.write([DGT_CLOCK_MESSAGE, 0x03, DGT_CMD_CLOCK_BEEP, 0x01, 0x00])
        pass