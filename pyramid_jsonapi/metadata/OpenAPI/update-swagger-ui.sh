#!/bin/bash
mkdir -p swagger-ui
# Script to download latest swagger-ui-dist index.html from github
wget -qO- https://github.com/swagger-api/swagger-ui/archive/master.tar.gz | tar -xvz --strip-components 2  -C swagger-ui --wildcards */dist/index.html

# CDN url
CDN_URL=https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.4.2/

# Convert html to template (adding CDN for JS libs)
sed -e "s|\./|$CDN_URL|" -e 's/url: ".*"/url: "\${openapi_url}"/' swagger-ui/index.html >swagger-ui/index.mako

