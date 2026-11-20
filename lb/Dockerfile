# nginx load balancer for Render (deployed as its own free Docker web service).
FROM nginx:1.27-alpine
COPY default.conf.template /etc/nginx/templates/default.conf.template
ENV PORT=10000
EXPOSE 10000
