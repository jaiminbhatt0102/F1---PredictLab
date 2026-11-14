import { Suspense, lazy, useEffect } from 'react'
import { SelectionProvider } from './data'
import { SiteFooter } from './layout/SiteFooter'
import { SiteHeader } from './layout/SiteHeader'
import { Loading } from './components/ui'
import { useLocation, type RouteName } from './router'

const Home = lazy(() => import('./pages/Home'))
const Predictions = lazy(() => import('./pages/Predictions'))
const Results = lazy(() => import('./pages/Results'))
const History = lazy(() => import('./pages/History'))
const HistoryDetail = lazy(() => import('./pages/History').then((m) => ({ default: ({ id }: { id: string }) => m.HistoryDetail({ id }) })))
const Drivers = lazy(() => import('./pages/Drivers'))
const DriverDetail = lazy(() => import('./pages/DriverDetail'))
const Teams = lazy(() => import('./pages/Teams'))
const TeamDetail = lazy(() => import('./pages/TeamDetail'))
const Calendar = lazy(() => import('./pages/Calendar'))
const RaceDetail = lazy(() => import('./pages/RaceDetail'))
const How = lazy(() => import('./pages/How'))
const Updates = lazy(() => import('./pages/Updates'))
const NotFound = lazy(() => import('./pages/NotFound'))

const TITLES: Record<RouteName, string> = {
  home: 'This weekend', predictions: 'Predictions', results: 'Results', history: 'Prediction history', historyDetail: 'Saved prediction',
  drivers: 'Drivers', driver: 'Driver', teams: 'Teams', team: 'Team', calendar: 'Calendar', race: 'Grand Prix', how: 'How it works', updates: 'Updates', notfound: 'Page not found',
}

function Routes() {
  const loc = useLocation()
  useEffect(() => {
    document.title = `${TITLES[loc.name]} | F1 PredictLab`
    document.getElementById('main')?.focus({ preventScroll: true })
  }, [loc.name, loc.path])
  switch (loc.name) {
    case 'home': return <Home />
    case 'predictions': return <Predictions />
    case 'results': return <Results />
    case 'history': return <History />
    case 'historyDetail': return <HistoryDetail id={loc.params.id} />
    case 'drivers': return <Drivers />
    case 'driver': return <DriverDetail code={loc.params.code.toUpperCase()} />
    case 'teams': return <Teams />
    case 'team': return <TeamDetail slug={loc.params.slug} />
    case 'calendar': return <Calendar />
    case 'race': return <RaceDetail season={Number(loc.params.season)} round={Number(loc.params.round)} />
    case 'how': return <How />
    case 'updates': return <Updates />
    default: return <NotFound />
  }
}

export default function App() {
  return (
    <SelectionProvider>
      <a className="skip" href="#main">Skip to content</a>
      <SiteHeader />
      <main id="main" className="page" tabIndex={-1}>
        <Suspense fallback={<Loading label="Loading the page" />}><Routes /></Suspense>
      </main>
      <SiteFooter />
    </SelectionProvider>
  )
}
