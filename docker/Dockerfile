FROM hysds/pge-base:latest

MAINTAINER malarout "Namrata.Malarout@jpl.nasa.gov"
LABEL description="Job to automate AOI creation and trigger rules"

ARG id
ARG gid


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
