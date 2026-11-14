import { Link } from '../router'

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div>
          <span className="brand"><span className="brand-mark" aria-hidden="true" />F1 PredictLab</span>
          <p>Qualifying, sprint and race predictions that update through the race weekend, kept apart from what actually happened.</p>
        </div>
        <div><h2>Weekend</h2><ul><li><Link to="/">This weekend</Link></li><li><Link to="/predictions">Predictions</Link></li><li><Link to="/results">Results</Link></li><li><Link to="/calendar">Calendar</Link></li></ul></div>
        <div><h2>Season</h2><ul><li><Link to="/drivers">Drivers</Link></li><li><Link to="/teams">Teams</Link></li><li><Link to="/history">Prediction history</Link></li></ul></div>
        <div><h2>About</h2><ul><li><Link to="/how-it-works">How it works</Link></li><li><Link to="/updates">Updates and status</Link></li></ul></div>
        <p className="footer-note">F1 PredictLab is an independent project. It is not affiliated with or endorsed by Formula 1, the FIA or any team. Predictions are estimates, not guarantees.</p>
      </div>
    </footer>
  )
}
