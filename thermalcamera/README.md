# thermalcamera

This is a simple thermal camera app using the AMG8833 (https://www.adafruit.com/product/3538) and PiTFT Plus 320x240 2.8" TFT + Resistive Touchscreen (https://www.adafruit.com/product/2298)

## Setup

 * Step 1: This app uses PyGame which should come installed on Raspian, otherwise use `pip install pygame`.

 * Step 2: Follow the instructions for installing the library for the AMG88xx at https://github.com/adafruit/Adafruit_AMG88xx
 
 * Step 3: Follow the instructions for installing the library for the PiTFT: https://learn.adafruit.com/adafruit-pitft-28-inch-resistive-touchscreen-display-raspberry-pi/easy-install-2
 
   The alternative if this doesn't work is the older script `adafruit-pitft-helper2.sh` found at https://github.com/adafruit/Adafruit-PiTFT-Helper
   
   