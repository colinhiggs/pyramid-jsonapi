from . import models
s = models.DBSession

class DBObjects():

    def __init__(self):
        self.alice = s.query(models.Person).get(1)
        self.bob = s.query(models.Person).get(2)
