from connection import connect,execute as _execute
def execute(client,code,payload=None,timeout=45):
 return _execute(client,code,payload,'qiming',timeout)
