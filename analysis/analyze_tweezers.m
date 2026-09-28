function result = analyze_tweezers(scanDir, parameterFile, outputDir)
% ANALYZE_TWEEZERS 与Python共用参数的单阱候选及离散Z观察，无额外工具箱。
% 先生成整体图像/指标，再检测参考帧。目标5000仅用于核对，不限定检测数量。
% 横向um是名义光学比例，轴向仍是物镜位置；离焦孔径计数包含邻阱混叠。
p=jsondecode(fileread(parameterFile)); s=p.spots; o=p.optics;
assert(s.algorithm_version==1);
for name={'gaussian_sigma_px','peak_threshold_counts','moment_threshold_sigma'}
    v=s.(name{1}); assert(isfinite(v) && v>0);
end
for name={'reference_point_id','gaussian_radius_px','maximum_filter_halfwidth_px', ...
        'aperture_radius_px','background_annulus_inner_px','background_annulus_outer_px'}
    v=s.(name{1}); assert(isfinite(v) && v>=1 && v==floor(v));
end
assert(s.aperture_radius_px<s.background_annulus_inner_px && s.background_annulus_inner_px<s.background_annulus_outer_px);
for name={'tube_lens_efl_mm','detection_objective_efl_mm','sensor_pixel_pitch_um','target_pitch_um'}
    v=o.(name{1});assert(isfinite(v) && v>0);
end
assert(p.operator_camera_settings.binning_horizontal==1 && p.operator_camera_settings.binning_vertical==1, '要求1x1 Binning');
overview=analyze_scan(scanDir,parameterFile,fullfile(outputDir,'overview'),false);
scanDir=overview.source;
cfg=jsondecode(fileread(fullfile(scanDir,'scan_config.json')));
assert(strcmp(cfg.horizontal_axis,'Z'),'需要Z扫描');
logs=readtable(fullfile(scanDir,'scan_log.csv'),'TextType','string','VariableNamingRule','preserve');
ref=find(overview.data(:,1)==s.reference_point_id);
assert(isscalar(ref) && strcmp(overview.status{ref},'ok'),'参考点没有可用TIFF');
j=find(logs.point_id==s.reference_point_id);
image=imread(safeFile(scanDir,logs.filename(j)));
[peaks,sensitivity]=detectSpots(image,p); k=size(peaks,1); assert(k>=2,'少于2个候选');
m=apertureMetrics(image,peaks(:,1:2),overview.data(ref,14),p);
assert(all(isfinite(m(:,9:10)),'all'),'参考峰有不可用质心');
magnification=o.tube_lens_efl_mm/o.detection_objective_efl_mm;
pixel_um=o.sensor_pixel_pitch_um/magnification; center=mean(m(:,9:10),1);
nearest=nearestDistances(m(:,9:10));
spots=[(1:k)' peaks m(:,9:10) (m(:,9:10)-center)*pixel_um m(:,3:8) nearest nearest*pixel_um];
detail=crop(image,s.detail_roi_xywh);
n=size(overview.data,1); probes=nan(n,k,8);
roi=p.signal_roi_xywh; stride=p.preview_stride;
observed_stack=nan(n,ceil(roi(4)/stride),ceil(roi(3)/stride));
for i=1:n
    if ~strcmp(overview.status{i},'ok'), continue; end
    j=find(logs.point_id==overview.data(i,1));
    if i==ref, frame=image; else, frame=imread(safeFile(scanDir,logs.filename(j))); end
    shift=overview.data(i,19:20)-overview.data(ref,19:20);
    measured=apertureMetrics(frame,peaks(:,1:2)+shift,overview.data(i,14),p);
    probes(i,:,:)=reshape(measured(:,1:8),[1 k 8]);
    preview=makePreview(crop(frame,roi),stride)-overview.data(i,13);
    observed_stack(i,:,:)=reshape(preview,[1 size(preview)]);
end
frame_info=overview.data(:,[1 5 8 19 20]);frame_info(:,4:5)=frame_info(:,4:5)-overview.data(ref,19:20);
calibration=[magnification pixel_um o.target_pitch_um/pixel_um center];
spot_columns={'spot_id','peak_x_px','peak_y_px','smoothed_peak_counts','centroid_x_px','centroid_y_px', ...
    'nominal_x_um','nominal_y_um','local_background_counts','aperture_net_sum','peak_net_counts', ...
    'clip_pixels','sigma_x_px','sigma_y_px','nearest_neighbor_px','nearest_neighbor_nominal_um'};
probe_columns={'anchor_x_px','anchor_y_px','local_background_counts','aperture_net_sum','peak_net_counts', ...
    'clip_pixels','sigma_x_px','sigma_y_px'};
status=overview.status;source=scanDir;parameters_json=fileread(parameterFile);
save(fullfile(outputDir,'tweezers.mat'),'spots','probes','observed_stack','frame_info','calibration', ...
    'sensitivity','spot_columns','probe_columns','status','parameters_json','source','-v7');
writetable(array2table(spots,'VariableNames',spot_columns),fullfile(outputDir,'reference_spots.csv'));
writetable(array2table(frame_info,'VariableNames',{'point_id','target_z_mm','planned_z_mm','global_dx_px','global_dy_px'}),fullfile(outputDir,'frame_info.csv'));
writetable(array2table(sensitivity,'VariableNames',{'threshold_counts','candidate_count'}),fullfile(outputDir,'threshold_sensitivity.csv'));
rows=[repelem(frame_info(:,1),k) repmat(spots(:,1),n,1) reshape(permute(probes,[2 1 3]),n*k,8)];
writetable(array2table(rows,'VariableNames',[{'point_id','spot_id'} probe_columns]),fullfile(outputDir,'aperture_probes.csv'));
result=struct('spots',spots,'probes',probes,'observed_stack',observed_stack,'frame_info',frame_info, ...
    'calibration',calibration,'sensitivity',sensitivity,'spot_columns',{spot_columns},'probe_columns',{probe_columns}, ...
    'status',{status},'parameters_json',parameters_json,'source',source);
renderFigures(result,detail,p,outputDir);
fprintf('Tweezer observations saved: %s\n',outputDir);
end

function file=safeFile(root,relative)
file=char(java.io.File(fullfile(root,strrep(char(relative),'\',filesep))).getCanonicalPath());
assert(startsWith(lower(file),[lower(root) filesep]),'图像路径越界');
end

function im=crop(image,roi)
roi=double(roi(:)');x=roi(1);y=roi(2);w=roi(3);h=roi(4);
assert(all(isfinite(roi)) && all(roi==floor(roi)) && min(roi)>=0 && w>=2 && h>=2 ...
    && x+w<=size(image,2) && y+h<=size(image,1),'ROI无效');
im=image(y+1:y+h,x+1:x+w);
end

function [peaks,sensitivity]=detectSpots(image,p)
% 分离高斯卷积：先横后纵，与Python相同零填充；之后二维窗口局部最大值。
s=p.spots;roi=double(crop(image,p.signal_roi_xywh));
q=-s.gaussian_radius_px:s.gaussian_radius_px;
kernel=exp(-q.^2/(2*s.gaussian_sigma_px^2));kernel=kernel/sum(kernel);
smooth=conv2(conv2(roi,kernel,'same'),kernel','same');
w=2*s.maximum_filter_halfwidth_px+1;
ismax=smooth==movmax(movmax(smooth,w,1),w,2);
margin=max([s.background_annulus_outer_px,s.maximum_filter_halfwidth_px,s.gaussian_radius_px]);
ismax(1:margin,:)=false;ismax(end-margin+1:end,:)=false;
ismax(:,1:margin)=false;ismax(:,end-margin+1:end)=false;
thresholds=s.sensitivity_thresholds_counts; sensitivity=zeros(numel(thresholds),2);
for i=1:numel(thresholds)
    sensitivity(i,:)=[thresholds(i) nnz(ismax & smooth>thresholds(i))];
end
[y,x]=find(ismax & smooth>s.peak_threshold_counts);
values=smooth(sub2ind(size(smooth),y,x));
peaks=[x-1+p.signal_roi_xywh(1) y-1+p.signal_roi_xywh(2) values];
peaks=sortrows(peaks,[2 1]); % MATLAB find是列优先，显式改为y/x顺序。
end

function out=apertureMetrics(image,centers,noise,p)
% 返回[K,10]：anchorXY、背景中位数、净积分、净峰、截顶数、sigmaXY、centroidXY。
s=p.spots;r=s.background_annulus_outer_px;[dx,dy]=meshgrid(-r:r,-r:r);
rr=dx.^2+dy.^2;ap=rr<=s.aperture_radius_px^2;
ann=rr>=s.background_annulus_inner_px^2 & rr<=r^2;
out=nan(size(centers,1),10);
for i=1:size(centers,1)
    if any(~isfinite(centers(i,:))),continue;end
    xy=floor(centers(i,:)+.5);x=xy(1);y=xy(2);out(i,1:2)=xy;
    if x-r<0 || y-r<0 || x+r>=size(image,2) || y+r>=size(image,1),continue;end
    patch=double(image(y-r+1:y+r+1,x-r+1:x+r+1));b=median(patch(ann));net=patch-b;
    values=patch(ap);out(i,3:6)=[b sum(net(ap)) max(values)-b nnz(values>=p.candidate_clip_count)];
    weight=net;weight(~(ap & net>s.moment_threshold_sigma*noise))=0;mass=sum(weight(:));
    if mass>0
        mx=sum(weight.*dx,'all')/mass;my=sum(weight.*dy,'all')/mass;
        out(i,7:10)=[sqrt(sum(weight.*(dx-mx).^2,'all')/mass) sqrt(sum(weight.*(dy-my).^2,'all')/mass) x+mx y+my];
    end
end
end

function nearest=nearestDistances(xy)
% 分块全配对，避免依赖Statistics Toolbox；排除自身，其余候选都参与。
k=size(xy,1);nearest=nan(k,1);
for start=1:128:k
    ids=start:min(start+127,k);
    distances=hypot(xy(ids,1)-xy(:,1)',xy(ids,2)-xy(:,2)');
    distances(sub2ind(size(distances),(1:numel(ids))',ids'))=inf;
    nearest(ids)=min(distances,[],2);
end
end

function out=makePreview(im,stride)
[h,w]=size(im);out=zeros(ceil(h/stride),ceil(w/stride));
for dy=1:stride
    for dx=1:stride
        a=double(im(dy:stride:end,dx:stride:end));
        out(1:size(a,1),1:size(a,2))=out(1:size(a,1),1:size(a,2))+a;
    end
end
out=out./(min(stride,h-(0:stride:h-1))'*min(stride,w-(0:stride:w-1)));
end

function renderFigures(res,detail,p,out)
spots=res.spots;f=figure('Visible','off','Position',[50 50 1600 500]);
cols=[11 10 16];titles={'Raw peak minus local background / counts','Local aperture net sum / counts','Nearest neighbor / nominal um'};
for j=1:3
    ax=subplot(1,3,j,'Parent',f);scatter(ax,spots(:,7),spots(:,8),4,spots(:,cols(j)),'filled');
    axis(ax,'equal');set(ax,'YDir','reverse');colorbar(ax);title(ax,titles{j});
    xlabel(ax,'Camera x / nominal object um');ylabel(ax,'Camera y / nominal object um');
end
sgtitle(f,sprintf('Reference point %d: %d detected candidates; gain %g dB reported', ...
    p.spots.reference_point_id,size(spots,1),p.operator_camera_settings.gain_db));
print(f,fullfile(out,'spot_maps.png'),'-dpng','-r150');close(f);
f=figure('Visible','off','Position',[50 50 800 700]);ax=axes(f);r=p.spots.detail_roi_xywh;
imagesc(ax,[r(1) r(1)+r(3)-1],[r(2) r(2)+r(4)-1],detail,p.spots.detail_display_counts(:)');
colormap(ax,gray(256));axis(ax,'image');hold(ax,'on');
scatter(ax,spots(:,5),spots(:,6),40,'MarkerEdgeColor',[1 .39 .28]);
xlim(ax,[r(1) r(1)+r(3)]);ylim(ax,[r(2) r(2)+r(4)]);set(ax,'YDir','reverse');
xlabel(ax,'x / pixel');ylabel(ax,'y / pixel');title(ax,'Independent peak detection (no forced target count)');
print(f,fullfile(out,'spot_detail.png'),'-dpng','-r150');close(f);
[~,idx]=min(sum(spots(:,7:8).^2,2));stride=p.preview_stride;r=p.signal_roi_xywh;
ix=floor((spots(idx,5)-r(1))/stride)+1;iy=floor((spots(idx,6)-r(2))/stride)+1;
[z,order]=sort(res.frame_info(:,2));cuts={squeeze(res.observed_stack(order,iy,:)),squeeze(res.observed_stack(order,:,ix))};
% 用每一采样平面的独立曲线，兼容非等距/重复Z，不虚构中间截面。
f=figure('Visible','off','Position',[50 50 1300 500]);names={'x','y'};
for j=1:2
    values=cuts{j};ax=subplot(1,2,j,'Parent',f);
    pos=(r(j)+((0:size(values,2)-1)+.5)*stride-.5-res.calibration(3+j))*res.calibration(2);
    plot(ax,pos,values');xlabel(ax,['Camera ' names{j} ' / nominal object um']);
    ylabel(ax,'Block mean minus background / counts');legend(ax,compose('Z=%.4f mm',z));grid(ax,'on');
end
sgtitle(f,'Sampled planes; fixed camera cuts; objective target Z, not calibrated object Z');
print(f,fullfile(out,'sampled_xz_yz.png'),'-dpng','-r150');close(f);
end
