FROM nginx:stable-alpine

RUN apk add --no-cache gettext

COPY . /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

CMD ["/bin/sh", "-c", "export PYRIT_API_URL=${PYRIT_API_URL:-/api/run-scan}; export PROMPTFOO_API_URL=${PROMPTFOO_API_URL:-/api/run-promptfoo}; envsubst '${PYRIT_API_URL} ${PROMPTFOO_API_URL}' < /usr/share/nginx/html/config.js.template > /usr/share/nginx/html/config.js && nginx -g 'daemon off;'"]
