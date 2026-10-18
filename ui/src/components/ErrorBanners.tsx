import { dismissNotice, useNotices } from "../errors/notices";

export function ErrorBanners() {
  const notices = useNotices();
  if (notices.length === 0) return null;
  return (
    <section className="banners" aria-live="assertive">
      {notices.map((notice) => (
        <div key={notice.key} className="banner" role="alert">
          <div className="banner-body">
            <strong>{notice.title}</strong>
            <span>{notice.message}</span>
            {notice.detail !== null && <code className="banner-detail">{notice.detail}</code>}
            {notice.errorId !== null && <span className="muted">Error ID {notice.errorId}</span>}
          </div>
          <button
            type="button"
            className="button ghost"
            aria-label="Dismiss"
            onClick={() => {
              dismissNotice(notice.key);
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </section>
  );
}
