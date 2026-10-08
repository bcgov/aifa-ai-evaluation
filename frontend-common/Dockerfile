FROM nginx:stable-alpine

RUN apk add --no-cache gettext

COPY . /usr/share/nginx/html

CMD ["/bin/sh", "-c", "envsubst '${PYRIT_API_URL} ${PROMPTFOO_API_URL}' < /usr/share/nginx/html/config.js.template > /usr/share/nginx/html/config.js && nginx -g 'daemon off;'"]
