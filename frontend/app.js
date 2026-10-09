import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client?deps=react@18.3.1";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

// ============================================================ справочники

const CATEGORY = { running: "Бег", strength: "Силовые", hybrid: "Гибрид" };
const ORDER_STATUS = {
  new: ["Ожидает оплаты", "warn"],
  paid: ["Оплачен", "ok"],
  shipped: ["Отправлен", "ok"],
  delivered: ["Получен", "ok"],
  cancelled: ["Отменён", "bad"],
};
const VERIFICATION = {
  draft: ["Документы не загружены", ""],
  pending: ["На проверке", "warn"],
  verified: ["Верифицирован", "ok"],
  rejected: ["Отклонён", "bad"],
};
const DELIVERY = { pickpoint: "Пункт выдачи", courier: "Курьер до двери", post: "Почта России" };
const PAYMENT = { card: "Банковская карта", sbp: "СБП", yoomoney: "ЮMoney" };
const DOC_TYPE = { inn: "ИНН", ogrn: "ОГРН / ОГРНИП", passport: "Паспорт" };

const money = (v) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v)) + " ₽";
const date = (v) => new Date(v).toLocaleDateString("ru-RU");
const days = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? "день" : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? "дня" : "дней"}`;

// ============================================================ API

const TOKEN_KEY = "sm_token";
const storage = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (t) => {
    try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch {}
  },
};

class ApiError extends Error {}

function errorText(detail, status) {
  if (!detail) return `Ошибка ${status}`;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d) => `${(d.loc || []).filter((x) => x !== "body").join(".")}: ${d.msg}`)
      .join("; ");
  return JSON.stringify(detail);
}

async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = storage.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) {
      storage.set(null);
      window.dispatchEvent(new Event("sm-logout"));
    }
    throw new ApiError(errorText(data?.detail, res.status));
  }
  return data;
}

async function openDocument(docId) {
  const res = await fetch(`/api/documents/${docId}/file`, {
    headers: { Authorization: `Bearer ${storage.get()}` },
  });
  if (!res.ok) throw new ApiError("Не удалось открыть документ");
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ============================================================ роутер

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(query)) };
}

function useRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

const go = (path) => { window.location.hash = path; };

function match(pattern, path) {
  const p = pattern.split("/");
  const s = path.split("/");
  if (p.length !== s.length) return null;
  const params = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(s[i]);
    else if (p[i] !== s[i]) return null;
  }
  return params;
}

// ============================================================ контекст приложения

const AppCtx = createContext(null);
const useApp = () => useContext(AppCtx);

function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    return fn()
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((e) => setState({ loading: false, data: null, error: e.message }));
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return [state, reload, (data) => setState({ loading: false, data, error: null })];
}

// ============================================================ общие компоненты

const Alert = ({ kind = "error", children }) =>
  children ? html`<div className=${`alert ${kind}`}>${children}</div>` : null;

const Pill = ([label, kind]) => html`<span className=${`pill ${kind}`}>${label}</span>`;

function Stars({ value }) {
  if (value == null) return html`<span className="muted small">нет оценок</span>`;
  const full = Math.round(value);
  return html`<span className="stars" title=${value}>
    ${[1, 2, 3, 4, 5].map((i) => html`<span key=${i} className=${i <= full ? "" : "off"}>★</span>`)}
  </span>`;
}

function Loading({ state, children }) {
  if (state.loading && !state.data) return html`<p className="muted">Загрузка…</p>`;
  if (state.error) return html`<${Alert}>${state.error}<//>`;
  return children(state.data);
}

function Thumb({ src, alt }) {
  return html`<div className="thumb">
    ${src ? html`<img src=${src} alt=${alt || ""} loading="lazy" />` : html`<span>нет фото</span>`}
  </div>`;
}

function Modal({ onClose, children }) {
  return html`<div className="modal-bg" onClick=${(e) => e.target === e.currentTarget && onClose()}>
    <div className="modal" role="dialog">${children}</div>
  </div>`;
}

function RequireRole({ roles, children }) {
  const { user } = useApp();
  if (!user)
    return html`<div className="empty">
      <p>Войдите, чтобы продолжить.</p>
      <a className="btn" href="#/login">Войти</a>
    </div>`;
  if (roles && !roles.includes(user.role))
    return html`<div className="empty">Раздел недоступен для вашей роли.</div>`;
  return children;
}

// ============================================================ P1: вход и регистрация

function LoginPage() {
  const { login } = useApp();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      login(await api("/auth/login", { method: "POST", body: form }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return html`<div className="card" style=${{ maxWidth: 420, margin: "20px auto" }}>
    <h1>Вход в аккаунт</h1>
    <form className="form" onSubmit=${submit}>
      <${Alert}>${error}<//>
      <label className="field"><span>E-mail</span>
        <input type="email" required autoComplete="email" value=${form.email}
          onInput=${(e) => setForm({ ...form, email: e.target.value })} />
      </label>
      <label className="field"><span>Пароль</span>
        <input type="password" required autoComplete="current-password" value=${form.password}
          onInput=${(e) => setForm({ ...form, password: e.target.value })} />
      </label>
      <button className="btn block" disabled=${busy}>Войти</button>
      <p className="muted small" style=${{ textAlign: "center" }}>
        Нет аккаунта? <a href="#/register">Зарегистрироваться</a>
      </p>
      <div className="alert info small">
        Демо: покупатель <b>alexey@demo.ru</b>, продавец <b>kaban@siberiancore.ru</b> — пароль
        <b> password123</b>. Администратор: <b>admin@sportmarket.ru</b> / <b>admin12345</b>.
      </div>
    </form>
  </div>`;
}

function RegisterPage() {
  const { login } = useApp();
  const [form, setForm] = useState({ first_name: "", email: "", password: "", password2: "", role: "customer" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.password2) return setError("Пароли не совпадают");
    setBusy(true);
    setError(null);
    try {
      const { password2, ...body } = form;
      login(await api("/auth/register", { method: "POST", body }), form.role === "seller" ? "/account" : "/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return html`<div className="card" style=${{ maxWidth: 420, margin: "20px auto" }}>
    <h1>Регистрация</h1>
    <form className="form" onSubmit=${submit}>
      <${Alert}>${error}<//>
      <div className="segmented">
        ${[["customer", "Я покупатель"], ["seller", "Я продавец"]].map(
          ([role, label]) => html`<button type="button" key=${role} className=${form.role === role ? "on" : ""}
            onClick=${() => setForm({ ...form, role })}>${label}</button>`
        )}
      </div>
      <label className="field"><span>Имя</span><input required value=${form.first_name} onInput=${set("first_name")} /></label>
      <label className="field"><span>E-mail</span><input type="email" required value=${form.email} onInput=${set("email")} /></label>
      <label className="field"><span>Пароль (не менее 8 символов)</span>
        <input type="password" required minLength="8" value=${form.password} onInput=${set("password")} /></label>
      <label className="field"><span>Повторите пароль</span>
        <input type="password" required value=${form.password2} onInput=${set("password2")} /></label>
      <button className="btn block" disabled=${busy}>Зарегистрироваться</button>
      <p className="muted small" style=${{ textAlign: "center" }}>Уже есть аккаунт? <a href="#/login">Войти</a></p>
    </form>
  </div>`;
}

// ============================================================ P5: каталог

function ProductCard({ p }) {
  return html`<a className="product-card" href=${`#/product/${p.id}`}>
    <${Thumb} src=${p.image_url} alt=${p.name} />
    <div className="body">
      <div className="price">${money(p.price)}</div>
      <div style=${{ fontWeight: 600 }}>${p.name}</div>
      <div className="row small"><${Stars} value=${p.rating} />
        ${p.reviews_count > 0 && html`<span className="muted">(${p.reviews_count})</span>`}</div>
      <div className="small muted">${p.seller.name}
        ${p.seller.is_verified && html` · <span className="verified">✓ проверен</span>`}</div>
      <div className="small muted">Доставка от ${days(p.delivery_days)}</div>
    </div>
  </a>`;
}

function CatalogPage({ query }) {
  const [q, setQ] = useState(query.q || "");
  const category = query.category || "";
  const [state] = useAsync(() => {
    const params = new URLSearchParams();
    if (query.q) params.set("q", query.q);
    if (category) params.set("category", category);
    return api(`/products?${params}`);
  }, [query.q, category]);
  const navigate = (next) => {
    const params = new URLSearchParams(Object.entries({ q: query.q || "", category, ...next }).filter(([, v]) => v));
    go(`/?${params}`);
  };
  return html`<div>
    <h1>Каталог экипировки</h1>
    <p className="muted">Только проверенные продавцы: документы каждого магазина проверены модератором.</p>
    <form className="search" onSubmit=${(e) => { e.preventDefault(); navigate({ q: q.trim() }); }}>
      <input type="search" placeholder="Поиск по названию: шорты, футболка, тайтсы…" value=${q}
        onInput=${(e) => setQ(e.target.value)} />
      <button className="btn">Найти</button>
    </form>
    <div className="chips">
      ${[["", "Все"], ...Object.entries(CATEGORY)].map(
        ([key, label]) => html`<button key=${key} className=${`chip ${category === key ? "on" : ""}`}
          onClick=${() => navigate({ category: key })}>${label}</button>`
      )}
    </div>
    <${Loading} state=${state}>${(items) =>
      items.length
        ? html`<div className="products">${items.map((p) => html`<${ProductCard} key=${p.id} p=${p} />`)}</div>`
        : html`<div className="empty">Ничего не найдено</div>`}<//>
  </div>`;
}

// ============================================================ P6: карточка товара

function Gallery({ media }) {
  const [idx, setIdx] = useState(0);
  if (!media.length) return html`<div className="gallery-main"><${Thumb} /></div>`;
  const cur = media[Math.min(idx, media.length - 1)];
  return html`<div>
    <div className="gallery-main">
      ${cur.media_type === "video"
        ? html`<video src=${cur.url} controls playsInline />`
        : html`<img src=${cur.url} alt="" />`}
    </div>
    ${media.length > 1 && html`<div className="gallery-thumbs">
      ${media.map((m, i) => html`<button key=${m.id} className=${i === idx ? "on" : ""} onClick=${() => setIdx(i)}>
        ${m.media_type === "video" ? "▶ видео" : html`<img src=${m.url} alt="" />`}
      </button>`)}
    </div>`}
  </div>`;
}

function SizeTableView({ table }) {
  if (!table || !table.rows?.length) return html`<p className="muted">Продавец не указал размерную таблицу.</p>`;
  return html`<div className="table-wrap"><table>
    <thead><tr>${table.headers.map((h, i) => html`<th key=${i}>${h}</th>`)}</tr></thead>
    <tbody>${table.rows.map((r, i) => html`<tr key=${i}>${r.map((c, j) => html`<td key=${j}>${c}</td>`)}</tr>`)}</tbody>
  </table></div>`;
}

function InstructionView({ ins, empty }) {
  if (!ins || !ins.steps.length) return html`<p className="muted">${empty}</p>`;
  return html`<ul className="steps">
    ${ins.steps.map((s) => html`<li key=${s.id}><b>${s.name}</b>${s.description && html`<div className="muted">${s.description}</div>`}</li>`)}
  </ul>`;
}

function ProductInfoTabs({ p }) {
  const [tab, setTab] = useState("sizes");
  const tech = p.instructions.find((i) => i.kind === "technology");
  const care = p.instructions.find((i) => i.kind === "care");
  const tabs = [["sizes", "Размерная таблица"], ["tech", "Технологии"], ["care", "Рекомендации по уходу"], ["composition", "Состав"]];
  return html`<div className="card">
    <div className="tabs">${tabs.map(([k, l]) => html`<button key=${k} className=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</div>
    ${tab === "sizes" && html`<${SizeTableView} table=${p.size_table} />`}
    ${tab === "tech" && html`<${InstructionView} ins=${tech} empty="Продавец не описал технологии." />`}
    ${tab === "care" && html`<${InstructionView} ins=${care} empty="Продавец не добавил рекомендации по уходу." />`}
    ${tab === "composition" && html`<p>${p.composition || html`<span className="muted">Состав не указан.</span>`}</p>`}
  </div>`;
}

function ProductPage({ id }) {
  const { user, refreshCart, toast } = useApp();
  const [state] = useAsync(() => api(`/products/${id}`), [id]);
  const [size, setSize] = useState(null);
  const [amount, setAmount] = useState(1);
  const [error, setError] = useState(null);

  const addToCart = async (p) => {
    if (!user) return go("/login");
    setError(null);
    try {
      await api("/cart/items", { method: "POST", body: { product_id: p.id, size, amount } });
      refreshCart();
      toast("Товар добавлен в корзину");
    } catch (e) {
      setError(e.message);
    }
  };

  return html`<${Loading} state=${state}>${(p) => {
    const sizes = (p.size_table?.rows || []).map((r) => r[0]).filter(Boolean);
    const needSize = sizes.length > 0 && !size;
    return html`<div className="stack">
      <a href="#/" className="small">← Каталог</a>
      <div className="product-layout">
        <${Gallery} media=${p.media} />
        <div className="stack">
          <div>
            <div className="pill">${CATEGORY[p.category]}</div>
            <h1 style=${{ marginTop: 8 }}>${p.name}</h1>
            <div className="row"><${Stars} value=${p.rating} />${p.reviews_count > 0 && html`<span className="muted small">${p.rating} · оценок: ${p.reviews_count}</span>`}</div>
          </div>
          <div className="price" style=${{ fontSize: 28 }}>${money(p.price)}</div>
          <div className="small">
            <div>Продавец: <b>${p.seller.name}</b> ${p.seller.is_verified && html`<span className="verified">✓ документы проверены</span>`}</div>
            <div>Срок доставки: <b>${days(p.delivery_days)}</b></div>
          </div>
          ${p.description && html`<p>${p.description}</p>`}
          ${sizes.length > 0 && html`<div>
            <div className="small" style=${{ fontWeight: 600, marginBottom: 6 }}>Размер</div>
            <div className="sizes">${sizes.map((s) => html`<button key=${s} className=${`size-btn ${size === s ? "on" : ""}`} onClick=${() => setSize(s)}>${s}</button>`)}</div>
          </div>`}
          ${(!user || user.role === "customer") && html`<div className="row">
            <div className="qty">
              <button onClick=${() => setAmount(Math.max(1, amount - 1))}>−</button>
              <span>${amount}</span>
              <button onClick=${() => setAmount(Math.min(99, amount + 1))}>+</button>
            </div>
            <button className="btn" disabled=${needSize} onClick=${() => addToCart(p)}>
              ${needSize ? "Выберите размер" : "В корзину"}
            </button>
          </div>`}
          <${Alert}>${error}<//>
        </div>
      </div>
      <${ProductInfoTabs} p=${p} />
      <div className="card">
        <h2>Оценки покупателей</h2>
        ${p.reviews.length
          ? p.reviews.map((r) => html`<div className="review" key=${r.id}>
              <div className="row"><${Stars} value=${r.rating} /><b>${r.author}</b><span className="muted small">${date(r.created_at)}</span></div>
              ${r.comment && html`<p style=${{ marginTop: 6 }}>${r.comment}</p>`}
            </div>`)
          : html`<p className="muted">Оценок пока нет. Их оставляют только покупатели, получившие заказ.</p>`}
      </div>
    </div>`;
  }}<//>`;
}

// ============================================================ P7: корзина и оформление заказа

function CartPage() {
  const { refreshCart } = useApp();
  const [state, , setCart] = useAsync(() => api("/cart"), []);
  const [form, setForm] = useState({ delivery_method: "courier", delivery_address: "", payment_method: "card" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const mutate = async (fn) => {
    setError(null);
    try {
      setCart(await fn());
      refreshCart();
    } catch (e) {
      setError(e.message);
    }
  };

  const checkout = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api("/orders", { method: "POST", body: form });
      refreshCart();
      window.location.href = res.payment_url;
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return html`<${Loading} state=${state}>${(cart) =>
    !cart.items.length
      ? html`<div className="empty"><p>Корзина пуста</p><a className="btn" href="#/">Перейти в каталог</a></div>`
      : html`<div className="grid-2">
        <div className="card">
          <h1>Корзина</h1>
          ${cart.items.map((i) => html`<div className="line" key=${i.id}>
            <${Thumb} src=${i.image_url} />
            <div>
              <a href=${`#/product/${i.product_id}`}><b>${i.name}</b></a>
              <div className="small muted">${i.size ? `Размер ${i.size} · ` : ""}${money(i.price)} · доставка ${days(i.delivery_days)}</div>
              <div className="row" style=${{ marginTop: 6 }}>
                <div className="qty">
                  <button disabled=${i.amount <= 1} onClick=${() => mutate(() => api(`/cart/items/${i.id}`, { method: "PATCH", body: { amount: i.amount - 1 } }))}>−</button>
                  <span>${i.amount}</span>
                  <button onClick=${() => mutate(() => api(`/cart/items/${i.id}`, { method: "PATCH", body: { amount: i.amount + 1 } }))}>+</button>
                </div>
                <button className="link-btn danger small" onClick=${() => mutate(() => api(`/cart/items/${i.id}`, { method: "DELETE" }))}>Удалить</button>
              </div>
            </div>
            <b>${money(i.price * i.amount)}</b>
          </div>`)}
          <p className="small muted" style=${{ marginTop: 12 }}>
            Ожидаемый срок доставки заказа: <b>${days(cart.max_delivery_days)}</b>
          </p>
        </div>
        <form className="card form" onSubmit=${checkout}>
          <h2>Оформление заказа</h2>
          <label className="field"><span>Способ доставки</span>
            <select value=${form.delivery_method} onChange=${(e) => setForm({ ...form, delivery_method: e.target.value })}>
              ${Object.entries(DELIVERY).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}
            </select>
          </label>
          <label className="field"><span>Адрес доставки</span>
            <input required minLength="5" placeholder="Город, улица, дом, квартира" value=${form.delivery_address}
              onInput=${(e) => setForm({ ...form, delivery_address: e.target.value })} />
          </label>
          <div>
            <div className="small" style=${{ fontWeight: 500, marginBottom: 6 }}>Способ оплаты</div>
            <div className="radio-list">
              ${Object.entries(PAYMENT).map(([k, v]) => html`<label key=${k}>
                <input type="radio" name="pay" checked=${form.payment_method === k} onChange=${() => setForm({ ...form, payment_method: k })} /> ${v}
              </label>`)}
            </div>
          </div>
          <${Alert}>${error}<//>
          <div className="total-bar"><span>${money(cart.total)}</span>
            <button className="btn" disabled=${busy}>Оплатить</button></div>
        </form>
      </div>`}<//>`;
}

function PaymentPage({ id, query }) {
  const { toast } = useApp();
  const [state, , setOrder] = useAsync(() => api(`/orders/${id}`), [id]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const pay = async () => {
    setBusy(true);
    setError(null);
    try {
      setOrder(await api(`/payments/test/${id}/pay`, { method: "POST" }));
      toast("Оплата прошла успешно");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return html`<${Loading} state=${state}>${(o) => html`<div className="card pay-box stack">
    <div className="yk-logo">ЮKassa</div>
    <div className="pill warn">тестовый режим</div>
    ${o.status === "new"
      ? html`<div className="stack">
          <p>Заказ №${o.id}<br /><span className="muted small">${query.payment_id || ""}</span></p>
          <div className="price" style=${{ fontSize: 30 }}>${money(o.total)}</div>
          <p className="muted small">${PAYMENT[o.payment_method]}</p>
          <${Alert}>${error}<//>
          <button className="btn block" disabled=${busy} onClick=${pay}>Оплатить ${money(o.total)}</button>
          <a href="#/account" className="small">Вернуться в магазин</a>
        </div>`
      : html`<div className="stack">
          <h2>${o.status === "cancelled" ? "Заказ отменён" : "Заказ оплачен ✓"}</h2>
          ${o.tracking_number && html`<p>Трек-номер: <b>${o.tracking_number}</b></p>`}
          <p className="muted">Подтверждение отправлено на e-mail. Ожидаемый срок доставки — ${days(o.estimated_delivery_days)}.</p>
          <a className="btn" href="#/account">Мои заказы</a>
        </div>`}
  </div>`}<//>`;
}

// ============================================================ оценка после получения

function RateModal({ order, onClose, onDone }) {
  const items = order.items.filter((i) => !order.rated_product_ids.includes(i.product_id));
  const [ratings, setRatings] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      for (const [pid, rating] of Object.entries(ratings))
        await api("/reviews", { method: "POST", body: { order_id: order.id, product_id: Number(pid), rating } });
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };
  return html`<${Modal} onClose=${onClose}>
    <h2>Оцените товары</h2>
    <p className="muted small">Оценки видят все покупатели — это основа честного рейтинга продавцов.</p>
    ${items.map((i) => html`<div key=${i.product_id} style=${{ margin: "14px 0" }}>
      <div><b>${i.product_name}</b>${i.size ? ` · ${i.size}` : ""}</div>
      <div className="star-input">${[1, 2, 3, 4, 5].map((s) => html`<button key=${s} aria-label=${`${s} из 5`}
        className=${(ratings[i.product_id] || 0) >= s ? "on" : ""}
        onClick=${() => setRatings({ ...ratings, [i.product_id]: s })}>★</button>`)}</div>
    </div>`)}
    <${Alert}>${error}<//>
    <div className="row spread" style=${{ marginTop: 16 }}>
      <button className="btn secondary" onClick=${onClose}>Позже</button>
      <button className="btn" disabled=${busy || !Object.keys(ratings).length} onClick=${submit}>Отправить оценку</button>
    </div>
  <//>`;
}

// ============================================================ P2: личный кабинет

function ProfileCard() {
  const { user, setUser, toast } = useApp();
  const [form, setForm] = useState({ first_name: user.first_name, last_name: user.last_name || "" });
  const [error, setError] = useState(null);
  const save = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      setUser(await api("/users/me", { method: "PATCH", body: { first_name: form.first_name, last_name: form.last_name || null } }));
      toast("Профиль сохранён");
    } catch (err) {
      setError(err.message);
    }
  };
  return html`<form className="card form" onSubmit=${save}>
    <h2>Профиль</h2>
    <div className="small muted">${user.email} · с ${date(user.created_at)}</div>
    <div className="form-2">
      <label className="field"><span>Имя</span><input required value=${form.first_name} onInput=${(e) => setForm({ ...form, first_name: e.target.value })} /></label>
      <label className="field"><span>Фамилия</span><input value=${form.last_name} onInput=${(e) => setForm({ ...form, last_name: e.target.value })} /></label>
    </div>
    <${Alert}>${error}<//>
    <div><button className="btn secondary">Сохранить</button></div>
  </form>`;
}

function OrderView({ o, actions }) {
  return html`<div className="order stack">
    <div className="row spread">
      <b>Заказ №${o.id} от ${date(o.created_at)}</b>
      ${Pill(ORDER_STATUS[o.status])}
    </div>
    <div className="small">
      ${o.items.map((i, k) => html`<div key=${k}>${i.product_name}${i.size ? ` (${i.size})` : ""} × ${i.amount} — ${money(i.price * i.amount)}</div>`)}
    </div>
    <div className="small muted">
      ${DELIVERY[o.delivery_method]} · ${o.delivery_address}
      ${o.tracking_number && html` · трек-номер <b>${o.tracking_number}</b>`}
    </div>
    <div className="row spread"><b>${money(o.total)}</b><div className="row">${actions}</div></div>
  </div>`;
}

function CustomerOrders() {
  const { toast } = useApp();
  const [state, reload] = useAsync(() => api("/orders"), []);
  const [rating, setRating] = useState(null);
  const [error, setError] = useState(null);
  const act = async (fn, after) => {
    setError(null);
    try {
      const o = await fn();
      await reload();
      after?.(o);
    } catch (e) {
      setError(e.message);
    }
  };
  return html`<div className="card stack">
    <h2>Мои заказы</h2>
    <${Alert}>${error}<//>
    <${Loading} state=${state}>${(orders) =>
      !orders.length
        ? html`<p className="muted">Заказов пока нет.</p>`
        : orders.map((o) => html`<${OrderView} key=${o.id} o=${o} actions=${html`
            ${o.status === "new" && html`
              <button className="btn secondary small" onClick=${() => act(() => api(`/orders/${o.id}/cancel`, { method: "POST" }))}>Отменить</button>
              <a className="btn small" href=${`#/pay/${o.id}`}>Оплатить</a>`}
            ${["paid", "shipped"].includes(o.status) && html`
              <button className="btn small" onClick=${() => act(() => api(`/orders/${o.id}/confirm-delivery`, { method: "POST" }), setRating)}>Я получил заказ</button>`}
            ${o.status === "delivered" && o.rated_product_ids.length < new Set(o.items.map((i) => i.product_id)).size && html`
              <button className="btn small" onClick=${() => setRating(o)}>Оценить товары</button>`}
          `} />`)}<//>
    ${rating && html`<${RateModal} order=${rating} onClose=${() => setRating(null)}
      onDone=${() => { setRating(null); reload(); toast("Спасибо за оценку!"); }} />`}
  </div>`;
}

function ShopProfile({ profile, onSaved }) {
  const { toast } = useApp();
  const [form, setForm] = useState({ name: profile?.name || "", description: profile?.description || "" });
  const [error, setError] = useState(null);
  const save = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      onSaved(await api("/seller/profile", { method: "PUT", body: form }));
      toast("Профиль магазина сохранён");
    } catch (err) {
      setError(err.message);
    }
  };
  return html`<form className="card form" onSubmit=${save}>
    <div className="row spread"><h2 style=${{ margin: 0 }}>Магазин</h2>${profile && Pill(VERIFICATION[profile.verification_status])}</div>
    ${!profile && html`<${Alert} kind="info">Заполните профиль магазина — это первый шаг к продажам.<//>`}
    <label className="field"><span>Название магазина / бренда</span><input required minLength="2" maxLength="50" value=${form.name} onInput=${(e) => setForm({ ...form, name: e.target.value })} /></label>
    <label className="field"><span>Описание</span><textarea maxLength="1000" value=${form.description} onInput=${(e) => setForm({ ...form, description: e.target.value })} /></label>
    <${Alert}>${error}<//>
    <div><button className="btn secondary">Сохранить</button></div>
  </form>`;
}

function Verification({ profile, onChanged }) {
  const [state, reload] = useAsync(() => api("/seller/documents"), [profile.verification_status]);
  const [docType, setDocType] = useState("inn");
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const locked = profile.verification_status === "verified";

  const upload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("document_type", docType);
    form.append("file", file);
    try {
      await api("/seller/documents", { method: "POST", form });
      e.target.reset();
      setFile(null);
      await reload();
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id) => {
    try {
      await api(`/seller/documents/${id}`, { method: "DELETE" });
      await reload();
      onChanged();
    } catch (err) {
      setError(err.message);
    }
  };

  const hint = {
    draft: ["warn", "Загрузите документы ИП/ООО — после проверки модератором товары появятся в каталоге."],
    pending: ["info", "Документы отправлены на проверку. Обычно это занимает до 2 рабочих дней."],
    verified: ["info", "Магазин верифицирован — покупатели видят отметку «документы проверены»."],
    rejected: ["error", `Верификация отклонена: ${profile.rejection_reason || "—"}. Загрузите исправленные документы.`],
  }[profile.verification_status];

  return html`<div className="card stack">
    <h2>Верификация продавца</h2>
    <${Alert} kind=${hint[0]}>${hint[1]}<//>
    <${Loading} state=${state}>${(docs) => docs.length > 0 && html`<div className="table-wrap"><table>
      <thead><tr><th>Документ</th><th>Файл</th><th>Загружен</th><th></th></tr></thead>
      <tbody>${docs.map((d) => html`<tr key=${d.id}>
        <td>${DOC_TYPE[d.document_type]}</td>
        <td><button className="link-btn" onClick=${() => openDocument(d.id).catch((e) => setError(e.message))}>${d.original_name}</button></td>
        <td>${date(d.uploaded_at)}</td>
        <td>${!locked && html`<button className="link-btn danger" onClick=${() => remove(d.id)}>Удалить</button>`}</td>
      </tr>`)}</tbody>
    </table></div>`}<//>
    ${!locked && html`<form className="row" onSubmit=${upload}>
      <select style=${{ width: "auto" }} value=${docType} onChange=${(e) => setDocType(e.target.value)}>
        ${Object.entries(DOC_TYPE).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}
      </select>
      <input type="file" accept=".pdf,.jpg,.jpeg,.png" style=${{ flex: 1, minWidth: 200 }} onChange=${(e) => setFile(e.target.files[0])} />
      <button className="btn" disabled=${!file || busy}>Загрузить</button>
    </form>`}
    <${Alert}>${error}<//>
  </div>`;
}

function SellerProducts({ profile }) {
  const [state] = useAsync(() => api("/seller/products"), []);
  return html`<div className="card stack">
    <div className="row spread">
      <h2 style=${{ margin: 0 }}>Мои товары</h2>
      <div className="row">
        <a className="btn secondary" href="#/seller/analytics">Отчёт о продажах</a>
        <a className="btn" href="#/seller/products/new">Добавить товар</a>
      </div>
    </div>
    ${profile.verification_status !== "verified" && html`<${Alert} kind="warn">Товары не видны в каталоге, пока магазин не пройдёт верификацию.<//>`}
    <${Loading} state=${state}>${(items) =>
      !items.length
        ? html`<p className="muted">Товаров пока нет.</p>`
        : html`<div className="products">${items.map((p) => html`<a key=${p.id} className="product-card" href=${`#/seller/products/${p.id}`}>
            <${Thumb} src=${p.image_url} />
            <div className="body"><b>${p.name}</b><div>${money(p.price)}</div><div className="row small"><${Stars} value=${p.rating} /></div>
            <span className="small">Редактировать →</span></div>
          </a>`)}</div>`}<//>
  </div>`;
}

function SellerOrders() {
  const [state, reload] = useAsync(() => api("/seller/orders"), []);
  const [error, setError] = useState(null);
  const setStatus = async (id, status) => {
    setError(null);
    try {
      await api(`/seller/orders/${id}/status`, { method: "PATCH", body: { status } });
      reload();
    } catch (e) {
      setError(e.message);
    }
  };
  return html`<div className="card stack">
    <h2>Заказы покупателей</h2>
    <${Alert}>${error}<//>
    <${Loading} state=${state}>${(orders) =>
      !orders.length
        ? html`<p className="muted">Заказов пока нет.</p>`
        : orders.map((o) => html`<${OrderView} key=${o.id} o=${o} actions=${html`
            ${o.status === "paid" && html`<button className="btn small" onClick=${() => setStatus(o.id, "shipped")}>Отметить отправленным</button>`}
            ${o.status === "shipped" && html`<button className="btn secondary small" onClick=${() => setStatus(o.id, "delivered")}>Отметить доставленным</button>`}
          `} />`)}<//>
  </div>`;
}

function SellerCabinet() {
  const [state, reload, setProfile] = useAsync(() => api("/seller/profile"), []);
  return html`<${Loading} state=${state}>${(profile) => html`<div className="stack">
    <div className="grid-2">
      <${ProfileCard} />
      <${ShopProfile} profile=${profile} onSaved=${setProfile} />
    </div>
    ${profile && html`<${Verification} profile=${profile} onChanged=${reload} />`}
    ${profile && html`<${SellerProducts} profile=${profile} />`}
    ${profile && html`<${SellerOrders} />`}
  </div>`}<//>`;
}

function AccountPage() {
  const { user } = useApp();
  return html`<${RequireRole} roles=${["customer", "seller", "admin"]}>
    <h1>Личный кабинет</h1>
    ${user?.role === "seller" && html`<${SellerCabinet} />`}
    ${user?.role === "customer" && html`<div className="stack"><${ProfileCard} /><${CustomerOrders} /></div>`}
    ${user?.role === "admin" && html`<div className="stack"><${ProfileCard} /><a className="btn" href="#/admin">Перейти к верификации продавцов</a></div>`}
  <//>`;
}

// ============================================================ P3: создание и редактирование товара

const sizeTableToText = (t) => (t ? [t.headers, ...t.rows].map((r) => r.join("; ")).join("\n") : "");
function textToSizeTable(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(";").map((c) => c.trim()));
  if (!lines.length) return null;
  return { headers: lines[0], rows: lines.slice(1) };
}

function StepsEditor({ title, hint, steps, onChange }) {
  const update = (i, k, v) => onChange(steps.map((s, j) => (j === i ? { ...s, [k]: v } : s)));
  return html`<div className="stack">
    <div><b>${title}</b><div className="muted small">${hint}</div></div>
    ${steps.map((s, i) => html`<div className="step-editor" key=${i}>
      <input placeholder="Заголовок" value=${s.name} onInput=${(e) => update(i, "name", e.target.value)} />
      <input placeholder="Пояснение" value=${s.description || ""} onInput=${(e) => update(i, "description", e.target.value)} />
      <button type="button" className="btn secondary small" onClick=${() => onChange(steps.filter((_, j) => j !== i))}>✕</button>
    </div>`)}
    <div><button type="button" className="btn secondary small" onClick=${() => onChange([...steps, { name: "", description: "" }])}>+ Добавить пункт</button></div>
  </div>`;
}

function MediaManager({ product, onChange }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const upload = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    setBusy(true);
    setError(null);
    try {
      let updated = product;
      for (const f of files) {
        const form = new FormData();
        form.append("file", f);
        updated = await api(`/seller/products/${product.id}/media`, { method: "POST", form });
      }
      onChange(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (m) => {
    try {
      onChange(await api(`/seller/products/${product.id}/media/${m.id}`, { method: "DELETE" }));
    } catch (err) {
      setError(err.message);
    }
  };
  return html`<div className="card stack">
    <h2>Фото и видео</h2>
    <p className="muted small">Покажите товар в движении: присед, выпад, бег. Первое фото — обложка в каталоге. Видео: mp4, webm, mov.</p>
    <div className="media-grid">
      ${product.media.map((m) => html`<div className="media-item" key=${m.id}>
        ${m.media_type === "video"
          ? html`<div className="thumb"><video src=${m.url} muted /></div>`
          : html`<${Thumb} src=${m.url} />`}
        <div className="row spread small">
          ${m.is_main ? html`<span className="pill ok">обложка</span>` : html`<span className="muted">${m.media_type === "video" ? "видео" : "фото"}</span>`}
          <button className="link-btn danger" onClick=${() => remove(m)}>Удалить</button>
        </div>
      </div>`)}
    </div>
    <label className="btn secondary" style=${{ width: "fit-content", opacity: busy ? 0.5 : 1 }}>
      ${busy ? "Загрузка…" : "Добавить файлы"}
      <input type="file" multiple hidden accept="image/*,video/mp4,video/webm,video/quicktime" disabled=${busy} onChange=${upload} />
    </label>
    <${Alert}>${error}<//>
  </div>`;
}

function ProductEditor({ id }) {
  const { toast } = useApp();
  const isNew = id === "new";
  const [state, , setProduct] = useAsync(() => (isNew ? Promise.resolve(null) : api(`/seller/products/${id}`)), [id]);
  return html`<${RequireRole} roles=${["seller"]}>
    <${Loading} state=${state}>${(product) => html`<${ProductForm} key=${product?.id || "new"} product=${product}
      onSaved=${(p) => { toast("Товар сохранён"); isNew ? go(`/seller/products/${p.id}`) : setProduct(p); }}
      onMedia=${setProduct} />`}<//>
  <//>`;
}

function ProductForm({ product, onSaved, onMedia }) {
  const [form, setForm] = useState({
    name: product?.name || "",
    description: product?.description || "",
    price: product?.price || "",
    category: product?.category || "hybrid",
    composition: product?.composition || "",
    delivery_days: product?.delivery_days || 5,
    is_active: product?.is_active ?? true,
  });
  const [sizeText, setSizeText] = useState(sizeTableToText(product?.size_table) || "Размер; Обхват талии, см\nM; 76–82\nL; 82–88");
  const steps = (kind) => product?.instructions.find((i) => i.kind === kind)?.steps.map(({ name, description }) => ({ name, description })) || [];
  const [tech, setTech] = useState(steps("technology"));
  const [care, setCare] = useState(steps("care"));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const clean = (list) => list.filter((s) => s.name.trim()).map((s) => ({ name: s.name.trim(), description: s.description?.trim() || null }));
    const instructions = [];
    if (clean(tech).length) instructions.push({ kind: "technology", name: "Технологии", steps: clean(tech) });
    if (clean(care).length) instructions.push({ kind: "care", name: "Рекомендации по уходу", steps: clean(care) });
    const body = {
      ...form,
      price: String(form.price).replace(",", "."),
      delivery_days: Number(form.delivery_days),
      description: form.description || null,
      composition: form.composition || null,
      size_table: textToSizeTable(sizeText),
      instructions,
    };
    try {
      const saved = product
        ? await api(`/seller/products/${product.id}`, { method: "PATCH", body })
        : await api("/seller/products", { method: "POST", body: (({ is_active, ...b }) => b)(body) });
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm("Удалить товар?")) return;
    try {
      await api(`/seller/products/${product.id}`, { method: "DELETE" });
      go("/account");
    } catch (err) {
      setError(err.message);
    }
  };

  return html`<div className="stack">
    <a href="#/account" className="small">← Личный кабинет</a>
    <h1>${product ? "Редактирование товара" : "Новый товар"}</h1>
    <form className="stack" onSubmit=${save}>
      <div className="card form">
        <h2>Основное</h2>
        <label className="field"><span>Название</span><input required minLength="2" maxLength="100" value=${form.name} onInput=${set("name")} /></label>
        <label className="field"><span>Описание</span><textarea value=${form.description} onInput=${set("description")} /></label>
        <div className="form-2">
          <label className="field"><span>Цена, ₽</span><input required inputMode="decimal" value=${form.price} onInput=${set("price")} /></label>
          <label className="field"><span>Категория</span>
            <select value=${form.category} onChange=${set("category")}>${Object.entries(CATEGORY).map(([k, v]) => html`<option key=${k} value=${k}>${v}</option>`)}</select></label>
          <label className="field"><span>Срок доставки, дней</span><input type="number" min="1" max="60" required value=${form.delivery_days} onInput=${set("delivery_days")} /></label>
        </div>
        <label className="field"><span>Состав ткани</span><input maxLength="500" placeholder="88% полиэстер, 12% эластан" value=${form.composition} onInput=${set("composition")} /></label>
        ${product && html`<label className="row small"><input type="checkbox" style=${{ width: "auto" }} checked=${form.is_active}
          onChange=${(e) => setForm({ ...form, is_active: e.target.checked })} /> Товар в продаже</label>`}
      </div>
      <div className="card form">
        <h2>Размерная таблица</h2>
        <p className="muted small">Первая строка — заголовки, далее по строке на размер. Ячейки разделяйте «;». Первый столбец — название размера, его выбирает покупатель.</p>
        <textarea rows="6" style=${{ fontFamily: "monospace" }} value=${sizeText} onInput=${(e) => setSizeText(e.target.value)} />
      </div>
      <div className="card stack">
        <h2>Технологии и уход</h2>
        <${StepsEditor} title="Технологии" hint="Плоские швы, влагоотвод, пропитки — за что покупатель платит." steps=${tech} onChange=${setTech} />
        <${StepsEditor} title="Рекомендации по уходу" hint="Отдельный блок, чтобы покупатель не пропустил: температура стирки, сушка." steps=${care} onChange=${setCare} />
      </div>
      <${Alert}>${error}<//>
      <div className="row spread">
        ${product ? html`<button type="button" className="btn danger" onClick=${remove}>Удалить товар</button>` : html`<span />`}
        <button className="btn" disabled=${busy}>${product ? "Сохранить изменения" : "Создать и перейти к фото"}</button>
      </div>
    </form>
    ${product && html`<${MediaManager} product=${product} onChange=${onMedia} />`}
    ${product && product.is_active && html`<a href=${`#/product/${product.id}`} className="small">Открыть карточку в каталоге →</a>`}
  </div>`;
}

// ============================================================ P4: аналитика продавца

function AnalyticsPage() {
  const [state] = useAsync(() => api("/seller/analytics"), []);
  return html`<${RequireRole} roles=${["seller"]}>
    <a href="#/account" className="small">← Личный кабинет</a>
    <h1 style=${{ marginTop: 8 }}>Отчёт о продажах</h1>
    <${Loading} state=${state}>${(a) => {
      const maxRevenue = Math.max(1, ...a.products.map((p) => Number(p.revenue)));
      return html`<div className="stack">
        <div className="kpis">
          <div className="kpi"><div className="label">Выручка</div><div className="value">${money(a.revenue)}</div></div>
          <div className="kpi"><div className="label">Продано единиц</div><div className="value">${a.units_sold}</div></div>
          <div className="kpi"><div className="label">Оплаченных заказов</div><div className="value">${a.orders_count}</div></div>
          <div className="kpi"><div className="label">Товаров с продажами</div><div className="value">${a.products_with_sales} / ${a.products_total}</div></div>
          <div className="kpi"><div className="label">Средний рейтинг</div><div className="value">${a.average_rating ?? "—"}</div></div>
        </div>
        <div className="card">
          <h2>Ваши товары</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>Товар</th><th>Продано</th><th>Выручка</th><th></th><th>Рейтинг</th></tr></thead>
            <tbody>${a.products.map((p) => html`<tr key=${p.product_id}>
              <td><a href=${`#/seller/products/${p.product_id}`}>${p.name}</a></td>
              <td>${p.units_sold}</td>
              <td>${money(p.revenue)}</td>
              <td style=${{ width: "25%" }}><div className="bar"><div style=${{ width: `${(Number(p.revenue) / maxRevenue) * 100}%` }} /></div></td>
              <td><${Stars} value=${p.rating} /> <span className="muted small">${p.reviews_count || ""}</span></td>
            </tr>`)}</tbody>
          </table></div>
          ${!a.products.length && html`<p className="muted">Добавьте товары, чтобы увидеть статистику.</p>`}
        </div>
      </div>`;
    }}<//>
  <//>`;
}

// ============================================================ администратор: верификация

function AdminPage() {
  const [filter, setFilter] = useState("pending");
  const [state, reload] = useAsync(() => api(`/admin/sellers${filter ? `?verification_status=${filter}` : ""}`), [filter]);
  const [reasons, setReasons] = useState({});
  const [error, setError] = useState(null);
  const decide = async (id, approve) => {
    setError(null);
    try {
      await api(`/admin/sellers/${id}/verification`, { method: "POST", body: { approve, reason: reasons[id] || null } });
      reload();
    } catch (e) {
      setError(e.message);
    }
  };
  return html`<${RequireRole} roles=${["admin"]}>
    <h1>Верификация продавцов</h1>
    <div className="chips">
      ${[["pending", "На проверке"], ["verified", "Верифицированы"], ["rejected", "Отклонены"], ["", "Все"]].map(
        ([k, l]) => html`<button key=${k} className=${`chip ${filter === k ? "on" : ""}`} onClick=${() => setFilter(k)}>${l}</button>`
      )}
    </div>
    <${Alert}>${error}<//>
    <${Loading} state=${state}>${(sellers) =>
      !sellers.length
        ? html`<div className="empty">Заявок нет</div>`
        : html`<div className="stack">${sellers.map((s) => html`<div className="card stack" key=${s.id}>
            <div className="row spread"><h2 style=${{ margin: 0 }}>${s.name}</h2>${Pill(VERIFICATION[s.verification_status])}</div>
            <div className="small muted">${s.user.first_name} · ${s.user.email} · с ${date(s.created_at)}</div>
            ${s.description && html`<p>${s.description}</p>`}
            <div>
              <b className="small">Документы</b>
              ${s.documents.length
                ? s.documents.map((d) => html`<div key=${d.id} className="small">
                    ${DOC_TYPE[d.document_type]}: <button className="link-btn" onClick=${() => openDocument(d.id).catch((e) => setError(e.message))}>${d.original_name}</button>
                    <span className="muted"> · SHA-256 ${d.file_hash?.slice(0, 12)}…</span></div>`)
                : html`<div className="small muted">не загружены</div>`}
            </div>
            ${s.documents.length > 0 && s.verification_status !== "verified" && html`<div className="row">
              <input style=${{ flex: 1, minWidth: 200 }} placeholder="Причина отказа (обязательна при отклонении)"
                value=${reasons[s.id] || ""} onInput=${(e) => setReasons({ ...reasons, [s.id]: e.target.value })} />
              <button className="btn secondary" onClick=${() => decide(s.id, false)}>Отклонить</button>
              <button className="btn" onClick=${() => decide(s.id, true)}>Одобрить</button>
            </div>`}
          </div>`)}</div>`}<//>
  <//>`;
}

// ============================================================ каркас

function Header({ path }) {
  const { user, cartCount, logout } = useApp();
  const link = (href, label, extra) => html`<a href=${`#${href}`} className=${path === href ? "active" : ""}>${label}${extra}</a>`;
  return html`<header className="header"><div className="header-inner">
    <a className="logo" href="#/">Sport<span>Market</span></a>
    <nav className="nav">
      ${link("/", "Каталог")}
      ${user?.role === "customer" && link("/cart", "Корзина", cartCount > 0 && html`<span className="badge-count">${cartCount}</span>`)}
      ${user?.role === "seller" && link("/seller/analytics", "Аналитика")}
      ${user?.role === "admin" && link("/admin", "Верификация")}
      ${user ? html`${link("/account", user.first_name)}<a href="#/" onClick=${logout}>Выйти</a>` : link("/login", "Войти")}
    </nav>
  </div></header>`;
}

function Router({ route }) {
  const { path, query } = route;
  let m;
  if (path === "/") return html`<${CatalogPage} query=${query} />`;
  if (path === "/login") return html`<${LoginPage} />`;
  if (path === "/register") return html`<${RegisterPage} />`;
  if ((m = match("/product/:id", path))) return html`<${ProductPage} id=${m.id} />`;
  if (path === "/cart") return html`<${RequireRole} roles=${["customer"]}><${CartPage} /><//>`;
  if ((m = match("/pay/:id", path))) return html`<${RequireRole} roles=${["customer"]}><${PaymentPage} id=${m.id} query=${query} /><//>`;
  if (path === "/account") return html`<${AccountPage} />`;
  if ((m = match("/seller/products/:id", path))) return html`<${ProductEditor} id=${m.id} />`;
  if (path === "/seller/analytics") return html`<${AnalyticsPage} />`;
  if (path === "/admin") return html`<${AdminPage} />`;
  return html`<div className="empty">Страница не найдена. <a href="#/">В каталог</a></div>`;
}

function App() {
  const route = useRoute();
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [cartCount, setCartCount] = useState(0);
  const [toastText, setToastText] = useState(null);

  const toast = useCallback((text) => {
    setToastText(text);
    setTimeout(() => setToastText(null), 2500);
  }, []);

  const refreshCart = useCallback(() => {
    api("/cart")
      .then((c) => setCartCount(c.items.reduce((s, i) => s + i.amount, 0)))
      .catch(() => setCartCount(0));
  }, []);

  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener("sm-logout", onLogout);
    if (storage.get()) api("/users/me").then(setUser).catch(() => {}).finally(() => setReady(true));
    else setReady(true);
    return () => window.removeEventListener("sm-logout", onLogout);
  }, []);

  useEffect(() => {
    if (user?.role === "customer") refreshCart();
    else setCartCount(0);
  }, [user, refreshCart]);

  const ctx = {
    user,
    setUser,
    cartCount,
    refreshCart,
    toast,
    login: ({ access_token, user }, next) => {
      storage.set(access_token);
      setUser(user);
      go(next || (user.role === "admin" ? "/admin" : user.role === "seller" ? "/account" : "/"));
    },
    logout: () => {
      storage.set(null);
      setUser(null);
    },
  };

  if (!ready) return html`<p className="boot">Загрузка…</p>`;
  return html`<${AppCtx.Provider} value=${ctx}>
    <${Header} path=${route.path} />
    <main className="main"><${Router} route=${route} /></main>
    ${toastText && html`<div className="toast">${toastText}</div>`}
  <//>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
