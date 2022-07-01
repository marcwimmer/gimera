from curses import wrapper

def yieldlist(method):
    def wrapper(*args, **kwargs):
        result = list(method(*args, **kwargs))
        return result
    return wrapper