import { EmptyState } from '../components/ui'
import { Link } from '../router'

export default function NotFound() {
  return (
    <EmptyState title="That page doesn’t exist" action={<Link className="btn primary" to="/">Back to this weekend</Link>}>
      The link may be old or mistyped. Use the menu to find what you were looking for.
    </EmptyState>
  )
}
