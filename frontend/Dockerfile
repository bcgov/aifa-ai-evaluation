FROM nginx:stable-alpine

# Only substitute our variables so nginx's own $vars are left untouched.
ENV NGINX_ENVSUBST_FILTER="^(PYRIT_UPSTREAM|PROMPTFOO_UPSTREAM|PROMPTFOO_RUN_TOKEN|NGINX_LOCAL_RESOLVERS)$" \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

RUN rm -f /etc/nginx/conf.d/default.conf
COPY index.html classic.html config.js.template /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --chmod=755 05-aifa-defaults.envsh /docker-entrypoint.d/05-aifa-defaults.envsh

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1/healthz || exit 1