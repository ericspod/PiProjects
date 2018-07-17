'''
Backup web application.

https://howtoraspberrypi.com/create-a-wi-fi-hotspot-in-less-than-10-minutes-with-pi-raspberry/
'''

#! /usr/bin/env python
from __future__ import print_function
import psutil
import pyudev
import threading
import time
import os
import shutil
import datetime
import filecmp
import json
from collections import defaultdict

import bottle
from bottle import get,request,run, redirect, response, template

BACKDIR=os.path.expanduser('~/backup') # parent directory for individual subdirectories

context = pyudev.Context()

def getSaveDir(root):
    '''Get a date-stamped save directory path rooted at `root'.'''
    return os.path.join(root,datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    

def enumAllFiles(rootdir):
    '''Yields all absolute path regular files in the given directory.'''
    for root, dirs, files in os.walk(rootdir):
        for f in sorted(files):
            yield os.path.join(root,f)
            

def getUnfoundFiles(src,dest):
    '''Return files found in `src' not present in `dest'.'''
    destfiles=defaultdict(list)
    srcfiles=[]
    
    for destfile in enumAllFiles(dest):
        base=os.path.basename(destfile)
        destfiles[base].append(destfile)
        
    for srcfile in enumAllFiles(src):
        base=os.path.basename(srcfile)
        if base not in destfiles or not any(filecmp.cmp(srcfile,d) for d in destfiles[base]):
            srcfiles.append(srcfile)
            
    return srcfiles
                

def listUSBMountpoints():
    '''List USB mountpoint directories, assuming these are automounted.'''
    
    # list removable devices
    removable = [d for d in context.list_devices(subsystem='block', DEVTYPE='disk') if d.attributes.asstring('removable') == "1"]
    result=set()
    
    for device in removable:
        # list device nodes for the partitions of this device
        partitions = [d.device_node for d in context.list_devices(subsystem='block', DEVTYPE='partition', parent=device)]
        
        # if this is the device for disk partition p add the mountpoint to the output list
        result.update(p.mountpoint for p in psutil.disk_partitions() if p.device in partitions)
                
    return list(sorted(result))
    

class BackupThread(threading.Thread):
	'''
	Backup processing thread. This performs the steps of 1) searching the source device for files compared to the 
	destination, 2) listing the files found to copy, 3) copying the files and keeping track of progress, and reporting 
	any errors. Status is represented in the members which state where in the process the thread is and progress.
	'''
    IDLE=0 # doing nothing
    SEARCH=1 # searching source device for files to backup
    DONESEARCH=2 # search done, waiting on waitEvent to trigger
    BACKUP=3 # doing the backup now
    DONEBACKUP=4 # backup down
    ERROR=5 # error encountered, exc has exception
    
    def __init__(self,src,dest):
        super(BackupThread,self).__init__()
        self.src=src # source directory
        self.dest=dest # destination root directory
        self.status=self.IDLE # current status
        self.numFiles=0 # number of files to copy
        self.currentFile=None # current file being copied
        self.numCopied=0 # number of files copied
        self.waitEvent=threading.Event() # once files are found the thread waits in this event before copying
        self.exc=None # raised exception
        self.doCopy=True # set this to False before setting the event to abort
        self.daemon=True # make this a daemon thread
        
    def abort(self):
        '''Abort the copy thread if the search has completed.'''
        if self.status==self.DONESEARCH:
            self.doCopy=False
            self.waitEvent.set()
        
    def run(self):
        try:
            print('Starting backup thread from',self.src,'to',self.dest)
            
            self.status=self.SEARCH
            srcfiles=getUnfoundFiles(self.src,self.dest)
            self.numFiles=len(srcfiles)
            
            print('Num files to backup:',self.numFiles)
            self.status=self.DONESEARCH
            
            if self.numFiles>0:
                self.waitEvent.wait()
                
                if not self.doCopy:
                    self.status=self.DONEBACKUP
                else:
                    self.status=self.BACKUP
                    destdir=getSaveDir(self.dest)
                    print('Backing up to',destdir)
                    
                    for i,src in enumerate(srcfiles):
                        self.currentFile=src
                        dest=os.path.join(destdir,os.path.relpath(src,self.src))
                        
                        print('Copying',src,'to',dest,i+1,'/',self.numFiles)
                        os.makedirs(os.path.dirname(dest),exist_ok=True)
                        shutil.copy2(src,dest)
                        self.numCopied=i+1
                
            self.status=self.DONEBACKUP
            print('Done')
        except Exception as e:
            self.exc=e
            self.status=self.ERROR
        

class USBMonitor(object):
    '''This monitors for USB devices and fills the member `mounts' with directories mounted from them.'''
    def __init__(self):
        self.mounts=set()
        self.doRun=True
        self.delay=1
        
    def run(self):
        while self.doRun:
            oldmounts=self.mounts
            self.mounts=listUSBMountpoints()
            
            for m in set(self.mounts).union(oldmounts):
                if m not in oldmounts:
                    self.addMount(m)
                elif m not in self.mounts:
                    self.removeMount(m)
           
            time.sleep(self.delay)
           
    def addMount(self,m):
        print('Added',m)
   
    def removeMount(self,m):
        print('Removed',m)
       
        
class MonitorThread(threading.Thread,USBMonitor):
    '''Create a threaded version of the monitor.'''
    def __init__(self):
        threading.Thread.__init__(self)
        USBMonitor.__init__(self)
        self.daemon=True 
        
    def run(self):
        USBMonitor.run(self)
        
        
mon=MonitorThread()
mon.start()

backupThread=None

# save the template to file every time the script is run, the reloader will notice when changes are made to it this way
with open('base.tpl','w') as o:
    o.write('''
<html>
<head>
  <title>Backup Server</title>
<style>
body{ 
    background:darkgray;
}

#outer{
    text-align:center;
}

#inner{
    background:white;
    width: 300px;
    display: inline-block;
    padding:5px;
    border-width:5px;  
    border-style:dashed;
    border-radius:5px;
    border-color: gray;
}
</style>
</head>
<body>
<div id="outer">
<div id="inner">
{{!base}}
</div>
</div>
</body>
</html>
    ''')


rootTemplate='''
% rebase('base.tpl')
<h1>Choose Backup Source:</h1>
<form action="/choose" method="GET">
% for i,m in enumerate(mounts):
    <input type="radio" name="mount" value="{{m}}" {{'checked="checked' if i==0 else ''}}>{{m}}<br/>
% end
<input value="Choose Source" type="submit" />
</form>
'''

progressTemplate='''
% rebase('base.tpl')

<script>
window.onload = function() {
  var elem = document.getElementById("progress");   
  var id = setInterval(frame, 1000);
  
  function frame() {
    var xmlhttp = new XMLHttpRequest();
    xmlhttp.onreadystatechange = function() {
        if (this.readyState == 4 && this.status == 200) {
            var res = JSON.parse(this.responseText);
            var numcopied=res.numcopied;
            var numfiles=res.numfiles;
            
            if(numcopied==numfiles){
                clearInterval(id);
            }
            
            elem.innerHTML="<h1>Status: "+res.status+"</h1>";
            elem.innerHTML+="<h2>Current File: "+res.currentfile+"</h2>";
            elem.innerHTML+="<h2>Copied: "+String(numcopied)+" / "+String(numfiles)+"</h2>";
            elem.innerHTML+="<h2><a href='/'>Home</a></h2>";
        }
    };
    xmlhttp.open("GET", "/status", true);
    xmlhttp.send();
  }
}
</script>

<div id='progress'>...</div>
'''

okCancelTemplate='''
% rebase('base.tpl')
<h1>Num files: {{numFiles}}</h1>
% if numFiles > 0:
    <form action="/start" method="GET">
    <input value="OK" type="submit" />
    </form>
    <a href="/cancel">Cancel</a>
% else:
    <a href="/">Home</a>
% end
'''


@get('/')
def root():
    if backupThread is not None and backupThread.isAlive() and backupThread.status>=BackupThread.BACKUP:
        return template(progressTemplate,numCopied=backupThread.numCopied,numFiles=backupThread.numFiles)
    else:
        return template(rootTemplate,mounts=mon.mounts)


@get('/choose')
def choose():
    global backupThread
    
    mount=request.params.get('mount')
    
    if not mount:
        redirect('/')
    else:
        base=os.path.basename(mount)
        backupThread=BackupThread(mount,os.path.join(BACKDIR,base))
        backupThread.start()
        
        while backupThread.status<=BackupThread.SEARCH: # wait for the search, too slow?
            time.sleep(0.1)
        
        print('Files to backup:',backupThread.numFiles)
        return template(okCancelTemplate,numFiles=backupThread.numFiles)
    
       
@get('/status')
def status():
    if backupThread is None or backupThread.status==BackupThread.DONEBACKUP:
        stat='Ready'
    elif backupThread.status==BackupThread.DONESEARCH:
        stat='Searched Files'
    elif backupThread.status==BackupThread.ERROR:
        stat='Error: %s'%backupThread.exc
    else:
        stat='Backing up'
        
    res={
        'status':stat,
        'numcopied':backupThread.numCopied if backupThread else 0,
        'numfiles':backupThread.numFiles if backupThread else 0,
        'currentfile':os.path.basename(backupThread.currentFile) if backupThread else ''
    }
    
    response.content_type = 'application/json'
    return json.dumps(res)
    
    
@get('/start')
def start():
    backupThread.waitEvent.set()    
    redirect('/')
    

@get('/cancel')
def cancel():
    global backupThread
    backupThread.abort()
    backupThread=None
    redirect('/')

    
if __name__=='__main__':
    run(host='0.0.0.0',port='8080',reloader=True)
