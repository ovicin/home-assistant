""" Demo platform that has two fake switchces. """
import mraa
from homeassistant.helpers.device import ToggleDevice
from homeassistant.const import STATE_ON, STATE_OFF, DEVICE_DEFAULT_NAME


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """ Find and return demo switches. """
    add_devices_callback([
        Relay('Sirena', STATE_OFF, 13)
    ])


class Relay(ToggleDevice):
    """ Provides a demo switch. """
    def __init__(self, name, state, pin):
        self._name = name or DEVICE_DEFAULT_NAME
        self._state = state
        self._output = mraa.Gpio(13)
        self._output.dir(mraa.DIR_OUT)

    @property
    def name(self):
        """ Returns the name of the device if any. """
        return self._name

    @property
    def state(self):
        """ Returns the name of the device if any. """
        return self._state

    @property
    def is_on(self):
        """ True if device is on. """
        return self._state == STATE_ON

    def turn_on(self, **kwargs):
        """ Turn the device on. """
        self._state = STATE_ON
        self._output.write(1)

    def turn_off(self, **kwargs):
        """ Turn the device off. """
        self._state = STATE_OFF
        self._output.write(0)
