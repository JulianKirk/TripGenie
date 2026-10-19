FROM nginx:alpine
# Where a browser reaches each student frontend; see default.conf.template.
ENV STUDENT1_UI_URL=http://localhost:8081 \
    STUDENT2_UI_URL=http://localhost:9003 \
    STUDENT3_UI_URL=http://localhost:8093 \
    STUDENT4_UI_URL=http://localhost:8084 \
    STUDENT5_UI_URL=http://localhost:8085
COPY default.conf.template /etc/nginx/templates/
COPY index.html theme.css /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
