# backupserver

This simple script is designed for backing up data from a USB device on a pi while being controlled through a web interface.
It uses Bottle to serve a application which copies files from USB mountpoints to a time-stamped directory, for example
backing up camera images from an SD card through a USB reader.

## Setup:

 * Step 1: Install Python 3 libraries

    sudo pip3 install pyudev psutil bottle
    
 * Step 2: Setup Raspberry Pi to operate as an access point (optional)
 
 The idea is to setup the pi to operate as its own wifi access point then connect to it using another device to access
 the web interface. This isn't strictly necessary but makes it portable.
 
 The easiest way is to install RaspAP by following the instructions at https://github.com/billz/raspap-webgui
 
 * Step 3: Set the script to run at startup
 
 Cron isn't the best way to do this but it's easy. Put this in your crontab file:
 
   @reboot python3 /path/to/backupserver.py 2>&1 > backupserver.log
 
When your pi restarts it should start the server immediately, you can then connect to the pi and access the server at 
http://10.3.141.1 if you've setup RaspAP.
