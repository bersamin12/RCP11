FROM alpine/git:2.47.2 AS buildings-source
ARG BUILDINGS_COMMIT=55abf579598ca81cae0a82f337350375958e6722
RUN git clone --depth 1 --branch v13.0.0 https://github.com/lbl-srg/modelica-buildings.git /source \
    && test "$(git -C /source rev-parse HEAD)" = "$BUILDINGS_COMMIT"

FROM alpine/git:2.47.2 AS modelica-source
ARG MODELICA_COMMIT=8ae3d35c24e519cb2996cab20f3b13daf2b0c50a
RUN git clone --depth 1 --branch v4.1.0 https://github.com/modelica/ModelicaStandardLibrary.git /source \
    && test "$(git -C /source rev-parse HEAD)" = "$MODELICA_COMMIT"

FROM openmodelica/openmodelica:v1.26.3-minimal
COPY --from=modelica-source /source/Modelica /opt/modelica/Modelica
COPY --from=modelica-source /source/ModelicaServices /opt/modelica/ModelicaServices
COPY --from=modelica-source /source/Complex.mo /opt/modelica/Complex.mo
COPY --from=buildings-source /source/Buildings /opt/modelica/Buildings
RUN ln -s Modelica "/opt/modelica/Modelica 4.1.0" \
    && ln -s ModelicaServices "/opt/modelica/ModelicaServices 4.1.0" \
    && ln -s Complex.mo "/opt/modelica/Complex 4.1.0.mo" \
    && ln -s Buildings "/opt/modelica/Buildings 13.0.0"
ENV OPENMODELICALIBRARY=/opt/modelica
LABEL org.opencontainers.image.title="RCP OpenModelica + Buildings" \
      org.opencontainers.image.version="om1.26.3-buildings13.0.0" \
      org.rcp.buildings.commit="55abf579598ca81cae0a82f337350375958e6722" \
      org.rcp.modelica.commit="8ae3d35c24e519cb2996cab20f3b13daf2b0c50a"
