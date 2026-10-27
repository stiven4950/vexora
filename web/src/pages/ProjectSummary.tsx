import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { groupStatus, groupVersions, megabytes, mmss, projectName, resolutionLabel, sheetDate } from "../api/format";
import type { Job } from "../api/types";
import { Icon } from "../components/Icon";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { Shell } from "../components/Shell";
import { ROUTES } from "../routes";
import styles from "./ProjectSummary.module.css";

/** El resumen de un proyecto: la última versión terminada, su ficha y accesos rápidos. */
export function ProjectSummary() {
  const { id: projectId = "" } = useParams();
  const [versions, setVersions] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .jobs()
      .then((all) => setVersions(groupVersions(all).find((g) => g.id === projectId)?.jobs ?? []))
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [projectId]);

  const latest = versions?.find((job) => job.status === "done");
  const cover = latest ?? versions?.[0];
  // La ficha del video subido está en la versión raíz.
  const root = versions?.find((job) => job.parent === null) ?? cover;
  const sidebar = cover ? (
    <ProjectSidebar
      projectId={projectId}
      title={projectName(cover)}
      when={sheetDate(cover.created)}
      thumbnail={cover.thumbnail_url ? `${cover.thumbnail_url}&original=true&first=true` : null}
      active="summary"
      state={versions && groupStatus(versions) === "processing" ? "processing" : "result"}
      onDownload={latest?.output_url ? () => window.location.assign(`${latest.output_url}&download=true`) : undefined}
    />
  ) : undefined;

  if (error || (versions && versions.length === 0)) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <div className={styles.empty}>
          <Icon name="alert" size={28} />
          <h2>No encontramos este proyecto</h2>
          <p>{error ?? "No hay versiones con este identificador."}</p>
          <Link to={ROUTES.library}>Volver a mis proyectos</Link>
        </div>
      </Shell>
    );
  }
  if (!versions || !cover || !root) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <p className={styles.empty}>Cargando proyecto…</p>
      </Shell>
    );
  }

  const resolution = resolutionLabel(root.video_width, root.video_height);
  const facts: [string, string][] = [
    ["Archivo", root.filename],
    ["Duración", root.video_seconds ? mmss(root.video_seconds) : "—"],
    ["Resolución", resolution ?? "—"],
    ["Tamaño", root.video_bytes ? megabytes(root.video_bytes) : "—"],
    ["Versiones", String(versions.length)],
  ];
  const editable = versions.find((job) => job.editable);

  return (
    <Shell sidebar={sidebar} footer={false}>
      <div className={styles.page}>
        <h1>{projectName(cover)}</h1>
        <div className={styles.grid}>
          <div className={styles.video}>
            {latest?.output_url ? (
              <video src={latest.output_url} poster={latest.thumbnail_url ? `${latest.thumbnail_url}&first=true` : undefined} controls playsInline preload="metadata" />
            ) : (
              <p>Aún no hay una versión terminada.</p>
            )}
          </div>
          <aside className={styles.card}>
            <h2>Ficha</h2>
            <dl>
              {facts.map(([term, value]) => (
                <div key={term}>
                  <dt>{term}</dt>
                  <dd title={value}>{value}</dd>
                </div>
              ))}
            </dl>
            <div className={styles.actions}>
              <Link to={ROUTES.versions(projectId)}>
                <Icon name="layers" size={16} /> Versiones
              </Link>
              {editable && (
                <Link to={`${ROUTES.edit(projectId)}?v=${editable.id}`}>
                  <Icon name="wand" size={16} /> Editar efectos
                </Link>
              )}
              {latest?.output_url && (
                <a href={`${latest.output_url}&download=true`}>
                  <Icon name="download" size={16} /> Descargar
                </a>
              )}
            </div>
          </aside>
        </div>
      </div>
    </Shell>
  );
}
