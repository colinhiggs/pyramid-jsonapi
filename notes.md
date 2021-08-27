# Notes

## Permissions

`{blogs/1}` has the following representation:

```python
{
  "type": "blogs",
  "id": "1",
  "attributes": {
    "title": "alice's blog",
    "content": "Welcome to alice's blog.",
    "secret_code": "secret"
  },
  "relationships": {
    "owner": {
      "data": {"type": "people", "id": "1"} # alice
    },
    "posts": {
      "data": [
        {"type": "posts", "id": "1"},
        {"type": "posts", "id": "2"}
      ]
    }
  }
}
```

### get

#### example: `GET /blogs/1`
View methdod: `get`

Permissions required in general:

  1. `GET` for each attribute value (via return of `get_pfilter(obj, resource=True, ...)` being `True` or `{'attributes': {'the_attribute'}}`); `False` will result in no resource (`HTTPForbidden` or `HTTPNotFound`).
  1. `GET` for each relationship or it will not appear.
  1. `GET` for each related item (via return of `get_pfilter(identifier, resource=False, ...)`) or it will not be returned (`meta` _might_ have list of items removed from return).
  1. `GET` for each resource in `included`; These will, in turn, be subject to the above permission rules.

Permissions required for `{blogs/1}`:

  1. `GET` permission on `{blogs/1}` to see that `{blogs/1}` exists.
     - `blogs1_GET_perms = blogs_view_class.pfilter[GET](blogs_view_instance, {blogs/1})`
     - `blogs1_GET_perms == True or isinstance(blogs1_GET_perms, dict)` for exists permission.
  1. `GET` permission on `{blogs/1}.title, content, secret_code` to see existence and value of `title`, `content`, `secret_code`.
     - `blogs1_GET_perms == True` or `'title' in blogs1_GET_perms['attributes']` etc.
  1. `GET` permission on `{blogs/1}.owner` to see that `{blogs/1}.owner` exists.
     1. `blogs1_GET_perms == True` or `'owner' in blogs1_GET_perms['attributes']`.
     1. `GET` permission on `{people/1}` or else resource identifier will not be added.
        1. `people1_GET_perms = people_view_class.pfilter[GET](blogs_view_instance, {people/1})`


Sketch of procedure:

  1. ask for `GET` permission to `{blogs/1}`:
  1. `True` gives access to the content of all attributes (`title`, `content`, and `secret_code`) and shows the _existence_ of all rels (`owner` and `posts`).
  1. `False` denies access to the whole resource. A config setting changes behaviour between forbidden error and pretending `{blogs/1}` doesn't exist.
  1. A dictionary in the form `{'attributes': {'title', 'content'}, 'relationships': {'posts'}}` gives the same level of access to selected attributes and relationships (access to the contents of listed attributes and existence of relationships).
  1. Now loop through all related items in _allowed_ relationships:
     1. Ask for `GET` permission to each related resource.
     1. `True` _or_ a dictionary means a resource identifier for that resource will be present in that relationship.
     1. `False` means a resource identifier will not be present.
     1. If a related resource's identifier is present in the relationship data then it may be included (if the request asked for it to be).
     1. Each included resource will be shown depending on `GET` permissions as above (but requested for the included resource).

#### example: `GET /blogs`
View method: `collection_get`

Permissions required:

Same as `GET /blogs/1` example above, but applied to each resource in `data`.

Sketch of procedure:

  1. `GET` permission checked for every resource in `data`.
  1. If `True`, add whole resource.
  1. If `False`, remove resource.
  1. If dictionary, modify resource and add.
  1. Check related resources for each primary resource in `data` as for `GET /blogs/1` above.
  1. Build `included` as for `GET /blogs/1` example above.

#### example: `GET /blogs/1/owner` (to_one rel)
View method: `related_get`

Permissions required:

  1. `GET` for `{blogs/1}` relationship `owner`.
     - Note: if no further permissions were enforced, this would result in returning the resource `{people/1}`.
  2. Same permissions required as outlined in the `GET /blogs/1` example above but for the `{people/1}` resource.

#### example: `GET /blogs/1/posts` (to_many rel)

Same as `GET/blogs/1/owner` above but loop over `people` results.

#### example: `GET /blogs/1/relationships/owner`
View method: `relationships_get`

Permissions required:

  1. `GET` for `{blogs/1}` relationship `owner`.
     - Note: if no further permissions were enforced, this would result in returning the resource identifier for `{people/1}`.
  2. `GET` for res id for `{people/1}` (`pfilter` result of `True` or any dictionary will do).
  3. `GET` as appropriate for any resources in `included`.

#### example: `GET /blogs/1/relationships/posts`
View method: `relationships_get`

Permissions required:

Pretty much the same as `GET /blogs/1/relationships/owner`

#### example: `POST /blogs [blogs_resource]`
View method: `collection_post`

Permissions required:

  1. `POST` for the supplied resource. `pfilter` return of `True` will allow the whole resource through; dictionary will strip any blocked attributes and rels before attempting to create the resource (which might result in failure); `False` will entirely block creation (HTTPForbidden).
  2. `POST` for the relationship for any supplied relationships.
  3. `POST` (if the the created resource will be added to a `to_many` relationship of the related resource) or `PATCH` (if the created resrouce will be the target of a `to_one` relationship of the related resource) for the reverse relationship of any resources in supplied relationships?

Illustrating creating a resource with supplied relationsips:

```json
POST /blogs
{
  "data": {
    "type": "blogs",
    "attributes": {
      "title": "A new blog"
    },
    "relationships": {
      "owner": {
        "data": {"type": "people", "id": "1"}
      },
      "posts": {
        "data": [
          {"type": "posts", "id": "1"},
          {"type": "posts", "id": "2"}
        ]
      }
    }
  }
}
```

(3) would imply that we need `POST` permission to add the new blog to `/people/1/relationships/blogs`. Similarly we would need `PATCH` permission to set this as the blog for each `posts/{id}/relationships/blog`.

#### example: `POST /blogs/1/relationships/posts [resource identifiers]`
View method: `relationships_post`

Assume `{posts/10}.owner` is currently `None` and `{posts/20}.owner` is currently `{blogs/2}`.

```json
POST /blogs/1/relationships/posts
{
  "data": [
    {"type": "posts", "id": "10"},
    {"type": "posts", "id": "20"},    
  ]
}
```

Permissions required:

  1. `POST` permission on `{blogs/1}.posts` to add `{posts/10}`.
    1. `PATCH` permission on `{posts/10}.blog` to set value to `{blogs/1}`.
  1. `POST` permission on `{blogs/1}.posts` to add `{posts/20}`.
    1. `PATCH` permission on `{posts/20}.blog` to set value to `{blogs/1}`.
    2. `DELETE` permission on `{blogs/2}.posts` to remove `{posts/20}`.


#### example: `PATCH /blogs/1`

Consider patching `{blogs/1}` as follows:

```json
PATCH /blogs/1
{
  "data": {
    "type": "blogs",
    "id": "1",
    "attributes": {
      "title": "A new title"
    },
    "relationships": {
      "owner": {
        "data": {"type": "people", "id": "2"}
      },
      "posts": {
        "data": [
          {"type": "posts", "id": "2"},
          {"type": "posts", "id": "3"}
        ]
      }
    }
  }
}
```

We assume that the `title` is changing, the `owner` is changing from `{people/1}` to `{people/2}`, and that the list of `posts` is changing from `[1,2]` to `[2,3]` (removing `{posts/1}` and adding `{posts/2}`).

Permissions required:

  1. `PATCH` permission to the `title` attribute.
  1. `PATCH` permission on `{blogs/1}.owner` to set value to `{people/2}`.
     1. `POST` permission on `{people/2}.blogs` to add `{blogs/1}`.
     1. `DELETE` permission on `{people/1}.blogs` to remove `{blogs/1}`
  1. `POST` permission on `{blogs/1}.posts` to add `{posts/3}`.
     1. `PATCH` permission on `{posts/3}.blog` to set value to `{blogs/1}`.
     1. `DELETE` permission on `{blogs/ID}.posts` to remove `{posts/3}` if `{posts/3}.blog` is currently `{blogs/ID}`.
  1. `DELETE` permission on `{blogs/1}.posts` to remove `{posts/1}`.
     1. `PATCH` permission on `{posts/1}.blog` to set value to `None/null`.

#### example: `PATCH /blogs/1/relationships/owner`

```json
PATCH /blogs/1/relationships/owner
{
  "data": {"type": "people", "id": "2"}
}
```

Permissions required:

  1. `PATCH` permission on `{blogs/1}.owner` to set value to `{people/2}`.
  1. `POST` permission on `{people/2}.blogs` to add `{blogs/1}`.
  1. `DELETE` permission on `{people/1}.blogs` to remove `{blogs/1}`.

#### example: `PATCH /blogs/1/relationships/posts`

Assume:
  - `{blogs/1}.posts` is currently `[{posts/1}, {posts/2}]`.
  - `{posts/3}.blog` is currently `None`.
  - `{posts/4}.blog` is currently `{blogs/2}`.

```json
PATCH /blogs/1/relationships/posts
{
  "data": [
    {"type": "posts", "id": "2"},
    {"type": "posts", "id": "3"},
    {"type": "posts", "id": "4"}
  ]
}
```

So this constitutes removing `{posts/1}` and adding `{posts/3}` and `{posts/4}`.

Permissions required:

  1. `DELETE` permission on `{blogs/1}.posts` to remove `{posts/1}`.
     1. `PATCH` permission on `{posts/1}.blog` to set value to `None`.
  1. `POST` permission on `{blogs/1}.posts` to add `{posts/3}`.
     1. `PATCH` permission on `{posts/3}.blog` to set value to `{blogs/1}`.
  1. `POST` permission on `{blogs/1}.posts` to add `{posts/4}`.
     1. `PATCH` permission on `{posts/4}.blog` to set value to `{blogs/1}`.
     1. `DELETE` permission on `{blogs/2}.posts` to remove `{posts/4}`.

#### example: `DELETE /blogs/1`

Assume `{blogs/1}` is as represented at the beginning of the permissions section.

Permissions required:

  1. `DELETE` permission on `{blogs/1}`.
     1. `DELETE` permission on `{people/1}.blogs` to remove `{blogs/1}`.
     1. `PATCH` permission on `{posts/1}.blog` to set value to `None`.
     1. `PATCH` permission on `{posts/2}.blog` to set value to `None`.

#### example: `DELETE /blogs/1/relationships/posts`

Permissions required:

1. `DELETE` permission on `{blogs/1}.posts` to remove `{posts/1}`.
   1. `PATCH` permission on `{posts/1}.blog` to set value to `None`.
1. `DELETE` permission on `{blogs/1}.posts` to remove `{posts/2}`.
   1. `PATCH` permission on `{posts/2}.blog` to set value to `None`.

### Permission Filters and Asking for Permission

Each model can have on permission filter per stage and possible permission. The possible permissions are the lower case versions of the HTTP verbs: `get`, `post`, `patch`, `delete`. They should have the signature:

`pfilter(target, mask, permission_sought, stage_name, view_instance)`

A workflow that is seeking permission for an action will call the registered `pfilter`.

mask = {
  'id': True,
  'attributes': {'att1': True, 'att2': False, ...},
  'relationships': {'rel1': False, 'rel2': True, ...}
}

mask = view.nothing_mask
mask = view.only_id_mask
mask = view.all_attributes_mask
mask = view.all_relationships_mask
mask = view.everything_mask

mask = view.attributes_mask(attributes)
mask = view.relationships_mask(relationships)

mask = view.mask_or(mask1, mask2)
mask = view.mask_and(mask1, mask2)

### Perm filters

params: obj_rep, view, stage, permission, mask, rep_type,


#### Example: post new person with blogs

post data:

{
  type: 'people',
  attributes: {
    name: 'alice',
    age: 42,
  },
  relationships: {
    blogs: {
      data: [
        blogs/1, blogs/2
      ]
    }
  }
}

1. authz post item to collection:

  pfilter(
    {type: people, id: None, atts: {...}},
    permission=post,
    mask=<all>,
    target=PermissionTarget(type=collection, name='people')
  )

1. authz post blogs to person.blogs:

  pfilter(
    {type: people, id: None, atts: {...}, rels: {
      blogs: { data: {blogs/1} } # note only one blog at a time so no array.
    }},
    permission=post,
    mask=<rel blogs>,
    target=PermissionTarget(type=relationship, name=blogs)
  )

1. authz reverse rel for blogs (owner):

  pfilter(
    {
      type: blogs, id: 1,
      rels: {owner: {type: people, id: None, atts: {...}}}
    },
    permission=patch,
    mask=<rel blogs>,
    target=PermissionTarget(type=relationship, name=owner)
  )

#### Example: patch person/1 with blogs

patch data:

{
  type: people,
  id: 1,
  attributes: {
    name: alice,
    age: 42,
  },
  relationships: {
    blogs: {
      data: [
        blogs/1, blogs/2
      ]
    }
  }
}

existing blogs: [blogs/2, blogs/3]

1. authz patch item:

  pfilter(
    {type: people, id: 1, atts: {...}},
    permission=patch,
    mask=<all>,
    target=PermissionTarget(type=item, name=None)
  )

1. authz delete blogs/3 from people/1.blogs:

  pfilter(
    {type: people, id: 1, atts: {...}, rels: {
      blogs: { data: {blogs/3} } # note only one blog at a time so no array.
    }},
    permission=delete,
    mask=<rel blogs>,
    target=PermissionTarget(type=relationship, name=blogs)
  )

1. authz patch blogs/3.owner to None:

  pfilter(
    {
      type: blogs, id: 3,
      rels: {owner: {data: None}}
    },
    permission=patch,
    mask=<rel owner>,
    target=PermissionTarget(type=relationship, name=owner)
  )
1. authz post blogs/1 to people/1.blogs:

  similar to delete of blogs/3, including patch of blogs/1.owner to people/1
