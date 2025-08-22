from .app import app

@app.task
def ping():
    return "pong"