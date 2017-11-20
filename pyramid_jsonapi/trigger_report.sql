select 
t.id, 
t.trigger_definition, 
i.identity_name,
t.active,
m.message,

    select count(distinct s.phone) 
    from sms_campaign_list
    where campaign_message_id = m.id

from 
triggers as t, 
identities as i,
campaign_triggers_assoc as a,
campaign_messages as m,
sms_campaign_list as s
WHERE
    a.trigger_id = t.id AND
    m.campaign_id = a.campaign_id AND
    t.type = 'event' AND
    i.user_id = t.create_user_id AND
    i.identity_type = 'email' AND
    message_type = 'sms' AND
    i.expire_date is NULL AND
    s.campaign_message_id = m.id
GROUP BY
    t.id, i.identity_name, m.message, m.id
LIMIT 10;