FROM hysds/pge-base:develop-es1

MAINTAINER malarout "Namrata.Malarout@jpl.nasa.gov"
LABEL description="Job to automate AOI creation and trigger rules"

ARG id
ARG gid

#Change UID and GID from build
USER root
# RUN set -ex && \
 #  usermod -u ${id} ops && \
 #  groupmod -g ${gid} ops && \
 #  chown -R ops:ops /home/ops/ /data && \
 #  usermod -g ${gid} ops

#install redis
RUN set -ex && \
  yum install -y redis

# create work directory
RUN set -ex \
 && mkdir -p /data/work \
 && chmod -R 755 /data \
 && chown -R ops:ops /data

# provision create_AOI PGE
USER ops
COPY . /home/ops/verdi/ops/megarules

# set entrypoint
WORKDIR /home/ops
CMD ["/bin/bash", "--login"]
