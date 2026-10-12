#include "diagnostics.h"

#include <pxr/external/boost/python.hpp>
#include <pxr/base/tf/pyError.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {
// The prim the current thread is reading, if any.
thread_local const SdfPath *currentSource = nullptr;
}  // namespace

const char *SeverityName(Severity severity) {
    switch (severity) {
    case Severity::Info:
        return "info";
    case Severity::Warning:
        return "warning";
    case Severity::Error:
        return "error";
    }
    return "error";
}

void RaiseTfErrors(const TfErrorMark &mark) {
    if (!mark.IsClean() && TfPyConvertTfErrorsToPythonException(mark)) pxr_boost::python::throw_error_already_set();
}

void HarvestErrors(const TfErrorMark &mark, const SdfPath &source, Diagnostics &out) {
    for (auto it = mark.begin(); it != mark.end(); ++it)
        out.push_back({Severity::Error, "tf-error", source, it->GetCommentary()});
    mark.Clear();
}

WarningCollector::WarningCollector() { TfDiagnosticMgr::GetInstance().AddDelegate(this); }

WarningCollector::~WarningCollector() { TfDiagnosticMgr::GetInstance().RemoveDelegate(this); }

void WarningCollector::IssueError(const TfError &error) { Add(Severity::Error, "tf-error", error.GetCommentary()); }

// Fatal errors end the process whatever a delegate does; there is nothing to record into.
void WarningCollector::IssueFatalError(const TfCallContext &, const std::string &) {}

void WarningCollector::IssueStatus(const TfStatus &) {}

void WarningCollector::IssueWarning(const TfWarning &warning) {
    Add(Severity::Warning, "tf-warning", warning.GetCommentary());
}

Diagnostics WarningCollector::Take() {
    Diagnostics taken;
    std::lock_guard<std::mutex> lock(mutex_);
    taken.swap(diagnostics_);
    return taken;
}

void WarningCollector::Add(Severity severity, const char *code, const std::string &message) {
    SdfPath source = currentSource ? *currentSource : SdfPath();
    std::lock_guard<std::mutex> lock(mutex_);
    diagnostics_.push_back({severity, code, std::move(source), message});
}

WarningCollector::ScopedSource::ScopedSource(const SdfPath &source) : previous_(currentSource) {
    currentSource = &source;
}

WarningCollector::ScopedSource::~ScopedSource() { currentSource = previous_; }

}  // namespace hydra_bridge
