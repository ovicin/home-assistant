""" Support for Infrared movement sensors. """

import mraa
from homeassistant.helpers.device import Device
from homeassistant.const import (
    TEMP_CELCIUS, ATTR_UNIT_OF_MEASUREMENT, ATTR_FRIENDLY_NAME)

# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Sets up the Demo sensors. """
    add_devices([
        MovementSensor('MiscareCasa', 0, 'BOOL', 13),
    ])

def movementISR(args):
	MovementSensor.UpdateState(args)
	
class MovementSensor(Device):
    """ A Demo sensor. """

    def __init__(self, name, state, unit_of_measurement, pin):
        self._name = name
        self._state = state
        self._unit_of_measurement = unit_of_measurement
        self._input = mraa.Gpio(pin)
        self._input.dir(mraa.DIR_IN)
        self._input.isr(mraa.EDGE_BOTH, movementISR, movementISR)

    @property
    def name(self):
        """ Returns the name of the device. """
        return self._name

    @property
    def state(self):
        """ Returns the state of the device. """
        return self._state

    @property
    def UpdateState(args):
        self._state = not self._input.read()
		
    @property
    def state_attributes(self):
        """ Returns the state attributes. """
        return {
            ATTR_FRIENDLY_NAME: self._name,
            ATTR_UNIT_OF_MEASUREMENT: self._unit_of_measurement,
        }
