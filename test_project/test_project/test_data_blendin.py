from test_project import models

def blendin(mixer):
    return {
        models.Person: {
            'name': mixer.faker.name,
        },
        models.Blog: {
            'title': mixer.faker.title,
        },
        models.Post: {
            'title': mixer.faker.title,
        },
        models.Comment: {
            'content': mixer.faker.paragraph,
        },
        models.BenignComment: {
            'content': mixer.faker.paragraph,
            'fawning_text': mixer.faker.sentence,
        }
    }
