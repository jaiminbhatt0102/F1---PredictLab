import { api } from '../api/client'
import { useFetch } from '../hooks/useFetch'
import { Banner, Disclosure, ErrorState, Loading, PageHeader } from '../components/ui'
import { Link } from '../router'

export default function How() {
  const status = useFetch((s) => api.status(s), [])
  const d = status.data?.data
  return (
    <>
      <PageHeader title="How it works" lead="What the app knows, when it predicts, and what it can’t know." />
      {status.error && <ErrorState error={status.error} onRetry={status.reload} />}
      {status.loading && <Loading />}
      {d && (
        <p className="panel">
          Right now the app has learned from <strong>{d.training_rows?.toLocaleString() ?? 'many'} driver results</strong> from the {d.seasons[0]} to {d.seasons[d.seasons.length - 1]} seasons, up to {d.latest_completed_event ? <strong>{d.latest_completed_event.race_name}</strong> : 'the latest race'}.
        </p>
      )}
      <section className="panel" aria-labelledby="h1">
        <h2 id="h1">Four moments, four predictions</h2>
        <p>The prediction changes as the weekend reveals more. Each one only uses what was known at that moment.</p>
        <ol className="steps">
          <li><strong>Before qualifying.</strong> Based on how drivers and teams have been doing in recent races and at this circuit. Nothing from this weekend.</li>
          <li><strong>Before the sprint</strong> (sprint weekends). The same idea, aimed at the sprint.</li>
          <li><strong>After qualifying.</strong> Now we know the qualifying result (and the sprint result on sprint weekends), so the race prediction becomes much sharper.</li>
          <li><strong>Before the race.</strong> The same, but using the official starting grid as soon as it is published, because penalties move drivers.</li>
        </ol>
      </section>
      <section className="panel" aria-labelledby="h2">
        <h2 id="h2">Kept up to date automatically</h2>
        <ol className="steps">
          <li><strong>Race week.</strong> The app saves a weather forecast every day, looks for new session results every couple of hours, and makes the predictions above as soon as they become possible.</li>
          <li><strong>After the race.</strong> The result is added, the prediction models learn from it, the weather that actually happened is saved, and the app is ready for the next Grand Prix.</li>
          <li><strong>Everything is saved.</strong> Each prediction is kept exactly as it was, then checked against the real result. That is how you can see whether to trust it.</li>
        </ol>
      </section>
      <section className="panel" aria-labelledby="h3">
        <h2 id="h3">About the weather</h2>
        <p>The app saves forecasts and the weather that really happened at every race, and uses them to build an experimental “with the weather forecast” version of the race prediction. It only runs with a forecast from the day before the race, which is as close as a forecast gets to what the cars will race in.</p>
        <p>So far, testing on past seasons hasn’t shown that weather makes the predictions clearly better, so it is offered as a beta and is never the main prediction. If that changes, it can be promoted by retraining, not by this website.</p>
      </section>
      <section className="panel" aria-labelledby="h5">
        <h2 id="h5">How do we know whether it works?</h2>
        <p>Two ways. First, every prediction is saved before the session and compared with the real result afterwards: <Link to="/history">Prediction history</Link> shows our record. Second, when the models are retrained they are tested on past seasons they never saw, never on data they learned from.</p>
        <Disclosure summary="Scoring terms, in plain words">
          <p><strong>Brier score</strong> measures how close predicted chances were to what happened. Lower is better. <strong>Log loss</strong> is similar but punishes confident wrong calls harder; lower is better. <strong>ROC-AUC</strong> measures how well the model puts drivers who did win ahead of those who did not; 0.5 is no better than guessing and 1 is perfect.</p>
          <p>These scores are used when training and are not shown on the site, because the record in Prediction history is easier to read.</p>
        </Disclosure>
      </section>
      <section className="panel" aria-labelledby="h4">
        <h2 id="h4">What a prediction cannot know</h2>
        <ul className="steps">
          <li>Crashes, safety cars, strategy calls, mechanical failures and first-lap chaos.</li>
          <li>Grid penalties, until the official grid is out.</li>
          <li>New drivers or teams that have not raced yet. The driver list is copied from the latest race, so check it against the confirmed entry list.</li>
        </ul>
        <Banner tone="neutral" title="Chances, not certainties">A driver with a 10% chance is expected to win about one race in ten. Even the favourite loses most of the time. Within one race, all the win chances add up to 100% and the podium chances to 300%, because there is one winner and three podium places.</Banner>
      </section>
    </>
  )
}
