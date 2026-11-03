// Diagnostics: Tf errors and warnings turned into records or Python exceptions, never stderr.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/tf/diagnosticMgr.h>
#include <pxr/base/tf/errorMark.h>
#include <pxr/usd/sdf/path.h>

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace hydra_bridge {

enum class Severity : std::uint8_t { Info, Warning, Error };

const char *SeverityName(Severity severity);

struct Diagnostic {
    Severity severity;
    std::string code;
    // A Hydra path in a snapshot; planning maps it to the USD source path.
    pxr::SdfPath source;
    std::string message;
};

using Diagnostics = std::vector<Diagnostic>;

// Modules defined with PXR_BOOST_PYTHON_MODULE don't get USD's automatic error
// conversion, so entry points raise the Tf errors posted since `mark` themselves.
void RaiseTfErrors(const pxr::TfErrorMark &mark);

// Moves the errors posted since `mark` into `out`, attributed to `source`.
void HarvestErrors(const pxr::TfErrorMark &mark, const pxr::SdfPath &source, Diagnostics &out);

// Collects Tf warnings, and errors posted outside any TfErrorMark, from every thread while
// installed. ScopedSource attributes them to the prim the posting thread is reading.
class WarningCollector final : public pxr::TfDiagnosticMgr::Delegate {
public:
    WarningCollector();
    ~WarningCollector() override;
    WarningCollector(const WarningCollector &) = delete;
    WarningCollector &operator=(const WarningCollector &) = delete;
    WarningCollector(WarningCollector &&) = delete;
    WarningCollector &operator=(WarningCollector &&) = delete;

    void IssueError(const pxr::TfError &error) override;
    void IssueFatalError(const pxr::TfCallContext &context, const std::string &message) override;
    void IssueStatus(const pxr::TfStatus &status) override;
    void IssueWarning(const pxr::TfWarning &warning) override;

    Diagnostics Take();

    class ScopedSource {
    public:
        explicit ScopedSource(const pxr::SdfPath &source);
        ~ScopedSource();
        ScopedSource(const ScopedSource &) = delete;
        ScopedSource &operator=(const ScopedSource &) = delete;
        ScopedSource(ScopedSource &&) = delete;
        ScopedSource &operator=(ScopedSource &&) = delete;

    private:
        const pxr::SdfPath *previous_;  // the source the thread read before this scope; null for none
    };

private:
    void Add(Severity severity, const char *code, const std::string &message);

    std::mutex mutex_;
    Diagnostics diagnostics_;
};

}  // namespace hydra_bridge
