ARG NGINX_BASE_IMAGE=nginxinc/nginx-unprivileged:1.29.4-alpine@sha256:a6c4f61f456b85b8fdf7ec7ab28cc3e299440e6fb4a9dea520e5fd8fd440025e
FROM ${NGINX_BASE_IMAGE}

ARG RELEASE_SHA
LABEL org.opencontainers.image.title="Reddit VOC Insights Site" \
      org.opencontainers.image.revision="${RELEASE_SHA}" \
      com.reddit-voc.component="insights-site" \
      com.reddit-voc.release="${RELEASE_SHA}"

USER root
RUN find /usr/share/nginx/html -mindepth 1 -delete

COPY --chown=101:101 deploy/insights/nginx.conf /etc/nginx/nginx.conf
COPY --chown=101:101 dist/ /usr/share/nginx/html/

RUN printf '{"release_sha256":"%s"}\n' "${RELEASE_SHA}" > /usr/share/nginx/html/release.json \
    && chown 101:101 /usr/share/nginx/html/release.json \
    && chmod 0444 /usr/share/nginx/html/release.json

USER 101:101
EXPOSE 8080
