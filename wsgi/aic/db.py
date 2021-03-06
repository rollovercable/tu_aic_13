import sqlalchemy
import sqlalchemy.ext.declarative
import sqlalchemy.orm
import settings
import datetime
from sqlalchemy import Table, Column, Integer, ForeignKey, String, DateTime, Boolean, func
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
import datetime as dt
from contextlib import contextmanager

engine = sqlalchemy.create_engine(settings.DB_URL)

Session = sqlalchemy.orm.sessionmaker(bind=engine)
Base = sqlalchemy.ext.declarative.declarative_base()

@contextmanager
def session_scope():
    session = Session()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

class Publication(Base):
    __tablename__ = 'publications'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    datetime = sqlalchemy.Column(sqlalchemy.DateTime)

    def __init__(self, datetime):
        self.datetime = datetime;

class Keyword(Base):
    __tablename__ = 'keywords'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    keyword = sqlalchemy.Column(sqlalchemy.String)
    tasks = relationship("Task")
    added = sqlalchemy.Column(sqlalchemy.DateTime)

    def __init__(self, keyword, added=dt.datetime.now()):
        self.keyword = keyword
        self.added = added

    def average_rating(self, session):
        return session.query(func.avg(Task.finished_rating))\
            .filter(Task.keyword_id == self.id)\
            .filter(Task.finished_rating != None)\
            .scalar()

    def num_mentions(self, session):
        return session.query(Task)\
            .filter(Task.keyword_id == self.id)\
            .filter(Task.finished_rating != None)\
            .count()

    def last_year_mentions(self, session):
        positive = self.last_year_mentions_by_rating(session, 10)
        neutral = self.last_year_mentions_by_rating(session, 5)
        negative = self.last_year_mentions_by_rating(session, 0)
        return {"positive": positive, "negative": negative, "neutral": neutral}

    def last_year_mentions_by_rating(self, session, rating):
        results = session.query("mon", "year","mentions").from_statement("""
            select extract(month from t.datetime) as mon,
                   extract(year from t.datetime) as year,
                   count(t) as mentions
            from tasks t
            where
                t.finished_rating = :rating and
                t.keyword_id = :id and
                t.datetime > CURRENT_DATE - INTERVAL '1 year'
            group by mon, year
        """).params(id=self.id, rating=rating).all()

        now = datetime.datetime.now()
        current_month = now.month
        current_year = now.year

        years = [current_year-1, current_year]
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        mentions = []
        count = 0

        # zeroing the months that have no data
        for year in years:
            for month in months:
                mentions.append(["%s %d" % (month, year), 0])

        # filling the months that have data
        for result in results:
            month, year, num_mentions = result
            year = int(year)
            month = int(month)
            year_index = years.index(year)
            count += num_mentions
            mentions[year_index*12+month-1][1] = num_mentions

        current_month_index = years.index(current_year)*12 + current_month
        return {"count": count, "data": mentions[current_month_index-12:current_month_index]}

class Project(Base):
    __tablename__ = 'projects'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    link = Column(sqlalchemy.String)
    datetime = sqlalchemy.Column(sqlalchemy.DateTime)
    paragraph = sqlalchemy.Column(sqlalchemy.String)

    tasks = relationship("Task")

    def __init__(self, paragraph, link, datetime=dt.datetime.now()):
        self.link = link
        self.paragraph = paragraph
        self.datetime = datetime

class Answer(Base):
    __tablename__ = 'answers'
    id = Column(sqlalchemy.Integer, primary_key=True)
    datetime = Column(sqlalchemy.DateTime)
    value = Column(sqlalchemy.String)
    task_id = Column(sqlalchemy.Integer, ForeignKey('tasks.id'))
    worker_id = Column(sqlalchemy.String, ForeignKey('workers.id'))

    def __init__(self, task, worker, value, datetime=dt.datetime.now()):
        self.task_id = task.id
        self.worker_id = worker.id
        self.datetime = datetime
        self.value = value

    def as_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'worker_id': self.worker_id,
            'datetime': self.datetime,
            'value': self.value
        }

class Worker(Base):
    __tablename__ = 'workers'
    id = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    # added for storing rating of workers
    worker_rating = sqlalchemy.Column(sqlalchemy.Integer)
    blocked = sqlalchemy.Column(sqlalchemy.Integer)
    first_seen = sqlalchemy.Column(sqlalchemy.DateTime)
    #
    answers = relationship("Answer")


    def __init__(self, worker_id, w_rating, w_blocked):
        """ provide the workerid from the mobile works system.
            it is assumed it is a string """
        self.id = worker_id
        self.worker_rating = w_rating
        self.blocked = w_blocked
        self.first_seen = dt.datetime.today()

class Task(Base):
    __tablename__ = 'tasks'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    paragraph =  Column(sqlalchemy.String)
    project_id = Column(sqlalchemy.Integer, ForeignKey('projects.id'))
    keyword_id = Column(sqlalchemy.Integer, ForeignKey('keywords.id'))
    finished_rating = sqlalchemy.Column(sqlalchemy.Integer)
    answers_requested = Column(Integer)
    price = Column(sqlalchemy.Float)
    price_bonus = Column(sqlalchemy.Float)
    datetime = Column(sqlalchemy.DateTime)
    garbage_flag = Column(sqlalchemy.Boolean)

    answers = relationship("Answer")

    def __init__(self, project, keyword, paragraph, datetime=dt.datetime.now()):
        self.project_id = project.id
        self.keyword_id = keyword.id
        self.paragraph = paragraph
        self.finished_rating = None
        self.price = 0.02
        self.price_bonus = 0
        self.datetime = datetime
        self.garbage_flag = False

    def calculate_rating(self):
        negative = 0
        positive = 0
        neutral = 0
        for answer in self.answers:
            if answer.value == 'negative':
                negative += 1
            elif answer.value == 'positive':
                positive += 1
            else:
                neutral += 1
        if positive > negative and positive > neutral:
            self.finished_rating = 10
        elif negative > positive and negative > neutral:
            self.finished_rating = 0
        else:
            self.finished_rating = 5

    def rate_workers(self):
        negative = 0
        positive = 0
        neutral = 0
        for answer in self.answers:
            if answer.value == 'negative':
                negative += 1
            elif answer.value == 'positive':
                positive += 1
            else:
                neutral += 1
        if positive > negative:
            m = positive
            ml = 'positive'
        else:
            m = negative
            ml = 'negative'
        if neutral > m :
            m = neutral
            ml ='neutral'
        session = Session()
        percentage = float(m)/(positive+neutral+negative)
        for answer in self.answers:
            worker = session.query(Worker).filter(Worker.id==answer.worker_id).first()
            if percentage >= 0.8:
                if answer.value == ml:
                    worker.worker_rating += 3
                else:
                    worker.worker_rating -= 2
            elif 0.5 < percentage < 0.8:
                if answer.value == ml:
                    worker.worker_rating += 1
                else:
                    worker.worker_rating -= 1
            else:
                worker.worker_rating -= 1
            if worker.worker_rating > 0:
                worker.worker_rating = 0
            #automatic blocking of bad workers
            if worker.worker_rating<-20:
                worker.blocked = 1
        session.commit()
        session.close()

Base.metadata.create_all(engine)

