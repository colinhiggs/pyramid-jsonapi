# Notes

## Permissions

`/blogs/1` has the following representation:

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

Permissions required:

  1. `GET` for each attribute value (via return of `get_pfilter(obj, resource=True, ...)` being `True` or `{'attributes': {'the_attribute'}}`); `False` will result in no resource (`HTTPForbidden` or `HTTPNotFound`).
  1. `GET` for each relationship or it will not appear.
  1. `GET` for each related item (via return of `get_pfilter(identifier, resource=False, ...)`) or it will not be returned (`meta` _might_ have list of items removed from return).
  1. `GET` for each resource in `included`; These will, in turn, be subject to the above permission rules.

Sketch of procedure:

  1. ask for `get` permission to `{blogs/1}`:
  1. `True` gives access to the content of all attributes (`title`, `content`, and `secret_code`) and shows the _existence_ of all rels (`owner` and `posts`).
  1. `False` denies access to the whole resource. A config setting changes behaviour between forbidden error and pretending `{blogs/1}` doesn't exist.
  1. A dictionary in the form `{'attributes': {'title', 'content'}, 'relationships': {'posts'}}` gives the same level of access to selected attributes and relationships (access to the contents of listed attributes and existence of relationships).
  1. Now loop through all related items in _allowed_ relationships:
    1. Ask for `get` permission to each related resource.
    1. `True` _or_ a dictionary means a resource identifier for that resource will be present in that relationship.
    1. `False` means a resource identifier will not be present.
    1. If a related resource's identifier is present in the relationship data then it may be included (if the request asked for it to be).
    1. Each included resource will be shown depending on `get` permissions as above (but requested for the included resource).

#### example: `GET /blogs`
View method: `collection_get`

Permissions required:

Same as `GET /blogs/1` example above, but applied to each resource in `data`.

Sketch of procedure:

  1. `get` permission checked for every resource in `data`.
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

Permissions required:

  1. `POST` permission to add each `post` resource identifier listed to the `posts` relationship of `{blogs/1}`.
  2. `PATCH` permission to alter the `blog` relationship of each `post` to `{blogs/1}`.


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

We assume that the `title` is changing, the `owner` is changing and that the list of `posts` is changing from `[1,2]` to `[2,3]` (removing `{posts/1}` and adding `posts/2`).

Permissions required:

  1. `PATCH` permission to the `title` attribute.
  1. `PATCH` permission on `{blogs/1}.owner` to set value to `{people/2}`.
    1. `POST` permission on `{people/2}.blogs` to add `{blogs/1}`.
  1. `POST` permission on `{blogs/1}.posts` to add `{posts/3}`.
    1. `PATCH` permission on `{posts/3}.blog` to set value to `{blogs/1}`.
  1. `DELETE` permission on `{blogs/1}.posts` to remove `{posts/1}`.
    1. `PATCH` permission on `{posts/1}.blog` to set value to `None/null`.

#### example: `PATCH /blogs/1/relationships/owner`

#### example: `PATCH /blogs/1/relationships/posts`

#### example: `DELETE /blogs/1`

#### example: `DELETE /blogs/1/relationships/posts`
