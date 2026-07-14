import { FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { login } from "../api/client";
import { ApiError } from "../api/errors";
import { useAuth } from "../app/useAuth";
import { Button, TextInput } from "../components/ui";

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!auth.loading && auth.user) {
    return <Navigate to="/downloads" replace />;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session = await login(username, password, rememberMe);
      auth.setAuthenticated(session.user, session.profiles, session.csrf_token);
      navigate("/downloads", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">
            ▶
          </span>
          <div>
            <p>yt-downloader</p>
            <strong>Audio LAN</strong>
          </div>
        </div>
        <div className="login-heading">
          <p className="eyebrow">Acceso privado</p>
          <h1 id="login-title">Iniciar sesión</h1>
          <p>Accede a tu biblioteca de audio.</p>
        </div>
        <form className="form-grid" onSubmit={submit}>
          <label className="field">
            <span>Usuario</span>
            <TextInput value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label className="field">
            <span>Contraseña</span>
            <TextInput type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </label>
          <label className="inline-check">
            <input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} />
            <span>Mantener sesión iniciada</span>
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <Button type="submit" className="button--wide" disabled={submitting}>{submitting ? "Entrando..." : "Entrar"}</Button>
        </form>
      </section>
    </main>
  );
}
