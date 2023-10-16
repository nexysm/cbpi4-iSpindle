
# -*- coding: utf-8 -*-
import os
from aiohttp import web, ClientSession, TCPConnector, ClientTimeout
import logging
from unittest.mock import MagicMock, patch
import asyncio
import random
from cbpi.api import *
from aiohttp import web
from cbpi.api import *
import re
import time
import json
from cbpi.api.dataclasses import DataType

logger = logging.getLogger(__name__)

cache = {}

async def calcGravity(polynom, tilt, unitsGravity):
	if unitsGravity == "SG":
		rounddec = 3
	else:
		rounddec = 2

	# Calculate gravity from polynomial
	tilt = float(tilt)
	result = eval(polynom)
	result = round(float(result),rounddec)
	return result

@parameters([Property.Text(label="iSpindle", configurable=True, description="Enter the name of your iSpindel"),
             Property.Select("Type", options=["Temperature", "Gravity/Angle", "Battery", "RSSI", "DateTime"], description="Select which type of data to register for this sensor. For Angle, Polynomial has to be left empty"),
             Property.Text(label="Polynomial", configurable=True, description="Enter your iSpindel polynomial. Use the variable tilt for the angle reading from iSpindel. Does not support ^ character."),
             Property.Select("Units", options=["SG", "Brix", "°P"], description="Displays gravity reading with this unit if the Data Type is set to Gravity. Does not convert between units, to do that modify your polynomial."),
             Property.Sensor("FermenterTemp",description="Select Fermenter Temp Sensor that you want to provide to TCP Server")])

class iSpindle(CBPiSensor):
    
    def __init__(self, cbpi, id, props):
        super(iSpindle, self).__init__(cbpi, id, props)
        self.value = 0
        self.key = self.props.get("iSpindle", None)
        self.Polynomial = self.props.get("Polynomial", "tilt")
        self.temp_sensor_id = self.props.get("FermenterTemp", None)
        self.datatype = DataType.DATETIME if self.props.get("Type", None) == "DateTime" else DataType.VALUE
        self.time_old = 0

    def get_unit(self):
        if self.props.get("Type") == "Temperature":
            return "°C" if self.get_config_value("TEMP_UNIT", "C") == "C" else "°F"
        elif self.props.get("Type") == "Gravity/Angle":
            return self.props.Units
        elif self.props.get("Type") == "Battery":
            return "V"
        elif self.props.get("Type") == "RSSI":
            return "dB"
        else:
            return " "

    async def run(self):
        global cache
        global fermenter_temp
        Spindle_name = self.props.get("iSpindle") 
        while self.running == True:
            try:
                if (float(cache[self.key]['Time']) > float(self.time_old)):
                    self.time_old = float(cache[self.key]['Time'])
                    if self.props.get("Type") == "Gravity/Angle":
                        self.value = await calcGravity(self.Polynomial, cache[self.key]['Angle'], self.props.get("Units"))
                    elif self.props.get("Type") == "DateTime":
                        self.value=float(cache[self.key]['Time'])
                    else:
                        self.value = float(cache[self.key][self.props.Type])
                    self.log_data(self.value)
                    self.push_update(self.value)
                self.push_update(self.value,False)
                #self.cbpi.ws.send(dict(topic="sensorstate", id=self.id, value=self.value))
                
            except Exception as e:
                pass
            await asyncio.sleep(2)

    def get_state(self):
        return dict(value=self.value)

class iSpindleEndpoint(CBPiExtension):
    
    def __init__(self, cbpi):
        '''
        Initializer
        :param cbpi:
        '''
        self.pattern_check = re.compile("^[a-zA-Z0-9,.]{0,10}$")
        self.cbpi = cbpi
        self.sensor_controller : SensorController = cbpi.sensor
        # register component for http, events
        # In addtion the sub folder static is exposed to access static content via http
        self.cbpi.register(self, "/api/hydrometer/v1/data")

    async def run(self):
        await self.get_spindle_sensor()

    @request_mapping(path='', method="POST", auth_required=False)
    async def http_new_value3(self, request):
        import time
        """
        ---
        description: Get iSpindle Value
        tags:
        - iSpindle 
        parameters:
        - name: "data"
          in: "body"
          description: "Data"
          required: "name"
          type: "object"
          type: string
        responses:
            "204":
                description: successful operation
        """

        global cache
        try:
            data = await request.json()
        except Exception as e:
            print(e)
        logging.info(data)
        time = time.time()
        key = data['name']
        temp = round(float(data['temperature']), 2)
        temp_units = data['temp_units']
        angle = data['angle']
        battery = data['battery']
        gravity = data['gravity']
        try:
            rssi = data['RSSI']
        except:
            rssi = 0
        cache[key] = {'Time': time,'Temperature': temp, 'Temp Units': temp_units, 'Angle': angle, 'Battery': battery, 'RSSI': rssi, "Gravity":gravity}

        return web.Response(status=204)


    @request_mapping(path='/gettemp/{SpindleID}', method="POST", auth_required=False)
    async def get_fermenter_temp(self, request):
        SpindleID = request.match_info['SpindleID']
        sensor_value = await self.get_spindle_sensor(SpindleID)
        data = {'Temp': sensor_value}
        return  web.json_response(data=data)

    async def get_spindle_sensor(self, iSpindleID = None):
        self.sensor = self.sensor_controller.get_state()
        for id in self.sensor['data']:
            if id['type'] == 'iSpindle':
                name= id['props']['iSpindle']
                if name == iSpindleID:
                    try:
                        sensor= id['props']['FermenterTemp']
                    except:
                        sensor = None
                    if (sensor is not None) and sensor != "":
                        sensor_value = self.cbpi.sensor.get_sensor_value(sensor).get('value')
                    else:
                        sensor_value = None
                    return sensor_value

@parameters([Property.Text(label="iSpindle", configurable=True, description="Enter the name of your iSpindel"),
             Property.Select("Service", options=["Brewersfriend"], description="Select the service type"),
             Property.Text(label="Token", configurable=True, description="Token"),
             Property.Text(label="Server", configurable=True, description="Enter the name of the server"),
             Property.Select("Units", options=["SG", "Brix", "°P"], description="Displays gravity reading with this unit if the Data Type is set to Gravity. Does not convert between units, to do that modify your polynomial.")
            ])

class iSpindleForwarder(CBPiSensor):
    
    def __init__(self, cbpi, id, props):
        super(iSpindleForwarder, self).__init__(cbpi, id, props)
        self.value = 0
        self.key = self.props.get("iSpindle", None)
        self.service = self.props.get("Service", None)
        self.token = self.props.get("Token", None)
        self.server = self.props.get("Server", None)
        self.unit = self.props.get("Units", None)
        self.time_old = 0

    async def run(self):
        global cache
        while self.running == True:
            try:
                if (float(cache[self.key]['Time']) > float(self.time_old)):
                    self.time_old = float(cache[self.key]['Time'])
                    if self.service == "Brewersfriend":
                        url = self.server + "/ispindel"
                        if self.unit == "SG":
                            url = url + "_sg"
                        url = url + "/" + self.token
                        name = self.key
                        temp = cache[self.key]['Temperature']
                        temp_unit = cache[self.key]['Temp Units']
                        angle = cache[self.key]['Angle']
                        battery = cache[self.key]['Battery']
                        gravity = cache[self.key]['Gravity']
                        rssi = cache[self.key]['RSSI']
                        if (self.unit == "SG"):
                            gravity_unit = "SG"
                        else:
                            gravity_unit = "P"

                        forward_data = {'name':name, 'temp':temp, 'temp_unit':temp_unit, 'gravity': gravity, 'battery':battery, 'RSSI': rssi}
                        # forward_data = {'name':name, 'temp':temp, 'gravity': gravity, 'battery':battery, 'RSSI': rssi}
                        logging.info(forward_data)

                        async with ClientSession(timeout=ClientTimeout(total=5), connector=TCPConnector(verify_ssl=False)) as session:
                            resp = await session.post(url, data=json.dumps(forward_data))

                            if resp.status == 200:
                                logging.info("Data uploaded to Brewersfriend")
                                self.push_update(temp)
                                self.log_data(temp)

            except Exception as e:
                logging.error("iSpindel Forwarder Eception" + str(e))
                pass

            await asyncio.sleep(2)

    def get_state(self):
        return dict(value=self.value)


def setup(cbpi):
    cbpi.plugin.register("iSpindle", iSpindle)
    cbpi.plugin.register("iSpindleForwarder", iSpindleForwarder)
    cbpi.plugin.register("iSpindleEndpoint", iSpindleEndpoint)
    pass
