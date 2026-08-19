/** Граница ошибок: сбой в одном экране не должен гасить приложение целиком.
 *
 *  Без неё любое исключение при отрисовке размонтирует всё дерево, и вместо
 *  интерфейса остаётся пустая белая страница — без единого слова о том, что
 *  произошло. Для платформы, куда загружают результаты обследования, это худший
 *  из возможных отказов: пользователь не знает, потерялись ли данные.
 *
 *  Текст ошибки показывается как есть. Прятать его «чтобы не пугать» здесь
 *  нечем: это внутренний контур клиники, а сообщение — единственное, с чем
 *  можно прийти к инженеру.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Консоль — не журнал, но единственное место, куда можно писать, не
    // обращаясь наружу (Р-23): отправка отчёта об ошибке во внешний сервис
    // была бы трансграничной передачей.
    console.error("сбой отрисовки", error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div style={{ padding: 32, maxWidth: 720, margin: "0 auto" }}>
        <h1 className="title">Экран не отрисовался</h1>
        <p className="subtitle">
          Данные на месте — сбой произошёл в отображении. Обновите страницу;
          если повторится, покажите инженеру текст ниже.
        </p>
        <div className="card">
          <div className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12.5 }}>
            {error.message}
          </div>
        </div>
        <button className="pill primary" style={{ marginTop: 16 }}
                onClick={() => this.setState({ error: null })}>
          Попробовать снова
        </button>
      </div>
    );
  }
}
