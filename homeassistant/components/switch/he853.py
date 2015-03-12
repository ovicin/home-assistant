""" Demo platform that has two fake switchces. """
from homeassistant.helpers import ToggleDevice
from homeassistant.const import STATE_ON, STATE_OFF, DEVICE_DEFAULT_NAME
from subprocess import call

# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """ Find and return demo switches. """
    add_devices_callback([
        DemoSwitch('Ovi Switch', STATE_ON),
        DemoSwitch('AC', STATE_OFF)
    ])


class HE853Switch(ToggleDevice):
    """ Provides a demo switch. """
    def __init__(self, name, state):
        self._name = name or DEVICE_DEFAULT_NAME
        self._state = state

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
        print(""" Turn the device on. """)
        call(["sudo","/home/pi/he853-remote/he853","2001","1"])
        self._state = STATE_ON

    def turn_off(self, **kwargs):
        print(""" Turn the device off. """)
        call(["sudo","/home/pi/he853-remote/he853","2001","0"])
        self._state = STATE_OFF
