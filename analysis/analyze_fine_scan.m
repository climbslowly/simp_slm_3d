function result=analyze_fine_scan(scanDir,parameterFile,outputDir)
% ANALYZE_FINE_SCAN 与fine_scan.py一致的201帧流式分析，无额外工具箱。
% 轴向单位是探测物镜规划位置；观察响应宽度不是已分离探测PSF的真实束腰。
p=jsondecode(fileread(parameterFile));scanDir=canonical(scanDir);outputDir=canonical(outputDir);
assert(~strcmpi(scanDir,outputDir) && ~startsWith(lower(outputDir),lower([scanDir filesep])));
assert(p.algorithm_version==1 && p.focus_half_window_um>0 && p.nominal_um_per_pixel>0);
assert(p.core_radius_px>0 && p.core_radius_px<=p.spots.aperture_radius_px && p.spots.aperture_radius_px<p.spots.background_annulus_inner_px && p.spots.background_annulus_inner_px<p.spots.background_annulus_outer_px);
c=jsondecode(fileread(fullfile(scanDir,'scan_config.json')));assert(c.schema_version==1 && strcmp(c.horizontal_axis,'Z'));
logs=readtable(fullfile(scanDir,'scan_log.csv'),'TextType','string','VariableNamingRule','preserve');
[~,ord]=sort([c.points.order_index]);points=c.points(ord);n=numel(points);
assert(height(logs)==n && numel(unique(logs.point_id))==n && numel(unique([points.point_id]))==n);
assert(numel(unique([points.order_index]))==n);
frames=nan(n,12);previews=nan(n,ceil(p.signal_roi_xywh(4)/p.preview_stride),ceil(p.signal_roi_xywh(3)/p.preview_stride));
files=cell(n,1);
for i=1:n
    j=find(logs.point_id==points(i).point_id);assert(isscalar(j) && logs.status(j)=="ok");
    files{i}=safeFile(scanDir,logs.filename(j));im=imread(files{i});m=load(safeFile(scanDir,logs.mat_filename(j)));
    assert(isa(im,'uint8') && ismatrix(im) && isequal(im,m.image) && m.point_id==points(i).point_id);
    expected=[points(i).targets_mm.X,points(i).targets_mm.Y,points(i).targets_mm.Z];
    assert(all(abs(double(m.target_xyz_mm(:)')-expected)<1e-9));
    assert(all(abs([logs.target_x_mm(j),logs.target_y_mm(j),logs.target_z_mm(j)]-expected)<1e-9));
    assert(m.exposure_us==logs.exposure_us(j));
    frames(i,:)=[points(i).point_id,expected(3),logs.actual_z_mm(j),logs.exposure_us(j),frameMetrics(im,p)];
    previews(i,:,:)=preview(crop(im,p.signal_roi_xywh),p.preview_stride);
    if mod(i-1,25)==0,fprintf('Overview %d/%d\n',i,n);end
end
assert(all(diff(frames(:,2))>0) && max(frames(:,4))==min(frames(:,4)));
[~,ref]=max(frames(:,10));im=imread(files{ref});[peaks,sensitivity]=detect(im,p);k=size(peaks,1);assert(k>1);
m=measure(im,peaks(:,1:2),frames(ref,6),p);[core,widths]=coreProfiles(im,m(:,1:2),m(:,3),p,true);
spots=[(1:k)',peaks,m,core,widths];
selected=find(abs((frames(:,2)-frames(ref,2))*1000)<=p.focus_half_window_um+1e-7);
probes=nan(numel(selected),k,5);registration=nan(numel(selected),4);
for j=1:numel(selected)
    i=selected(j);im=imread(files{i});shift=[0,0];
    for iteration=1:3
        trial=measure(im,peaks(:,1:2)+shift,frames(i,6),p);
        ok=all(isfinite(trial(:,9:10)),2) & trial(:,5)>.10*m(:,5);
        assert(nnz(ok)>=k/2,'可配准光点不足，需缩小近焦窗口');
        shift=median(trial(ok,9:10)-m(ok,9:10),1);
    end
    a=measure(im,peaks(:,1:2)+shift,frames(i,6),p);[v,~]=coreProfiles(im,a(:,1:2),a(:,3),p,false);
    ok=all(isfinite(a(:,9:10)),2) & a(:,5)>.10*m(:,5);
    residual=a(ok,9:10)-m(ok,9:10)-shift;
    registration(j,:)=[shift,nnz(ok),sqrt(mean(sum(residual.^2,2)))];
    probes(j,:,:)=[a(:,5),a(:,4),v,a(:,9:10)];
end
axial=nan(k,8);zz=frames(selected,2);ridx=find(selected==ref);
for j=1:k
    v=probes(:,j,3);[pk,i]=max(v);width=halfWidth(zz*1000,v);rv=v(ridx);ties=nnz(v==pk);
    valid=all(isfinite(v)) && isfinite(width) && pk>0 && ties==1;
    ratio=NaN;if rv>0,ratio=pk/rv;end
    axial(j,:)=[j,zz(i),width,pk,rv,ratio,double(valid),ties];
end
frame_columns={'point_id','target_z_mm','planned_z_mm','exposure_us','background_mean','background_std', ...
    'image_max','clip_pixels','roi_net_sum','gradient_energy','centroid_x_px','centroid_y_px'};
probe_columns={'local_peak','aperture_net_sum','core_net_sum','centroid_x_px','centroid_y_px'};
result=struct('frames',frames,'previews',previews,'reference_index',ref,'spots',spots,'sensitivity',sensitivity, ...
    'selected_indices',selected,'probes',probes,'registration',registration,'axial',axial,'source',scanDir,'parameters_json',fileread(parameterFile), ...
    'frame_columns',{frame_columns},'probe_columns',{probe_columns});
if ~isfolder(outputDir),mkdir(outputDir);end
save(fullfile(outputDir,'fine.mat'),'-struct','result','-v7');
writetable(array2table(frames,'VariableNames',frame_columns),fullfile(outputDir,'frames.csv'));
writetable(array2table(axial,'VariableNames',{'spot_id','peak_z_mm','core_response_fwhm_um','peak_core','reference_core','ratio','valid','peak_ties'}),fullfile(outputDir,'axial.csv'));
writetable(array2table(spots,'VariableNames',{'spot_id','peak_x_px','peak_y_px','smoothed_peak','anchor_x_px','anchor_y_px','local_background', ...
    'aperture_net_sum','peak_net','clip_pixels','sigma_x_px','sigma_y_px','centroid_x_px','centroid_y_px','core_net_sum','fwhm_x_px','fwhm_y_px'}),fullfile(outputDir,'spots.csv'));
fprintf('Reference ID %d, Z %.4f mm, %d candidates\n',frames(ref,1),frames(ref,2),k);
end

function v=frameMetrics(im,p)
bg=double(crop(im,p.background_roi_xywh));b=mean(bg(:));noise=std(bg(:),1);
roi=double(crop(im,p.signal_roi_xywh));net=roi-b;w=net;w(net<=p.threshold_sigma*noise)=0;mass=sum(w(:));
cx=NaN;cy=NaN;
if mass>0
    cx=sum(sum(w,1).*((0:size(w,2)-1)+p.signal_roi_xywh(1)))/mass;
    cy=sum(sum(w,2).*((0:size(w,1)-1)'+p.signal_roi_xywh(2)))/mass;
end
dx=diff(roi,1,2);dy=diff(roi,1,1);
v=[b,noise,double(max(im(:))),nnz(im>=p.candidate_clip_count),sum(net(:)),mean(dx(:).^2)+mean(dy(:).^2),cx,cy];
v=double(v);
end
function [peaks,sensitivity]=detect(im,p)
s=p.spots;roi=double(crop(im,p.signal_roi_xywh));q=-s.gaussian_radius_px:s.gaussian_radius_px;
g=exp(-q.^2/(2*s.gaussian_sigma_px^2));g=g/sum(g);
smooth=conv2(conv2(roi,g,'same'),g','same');w=2*s.maximum_filter_halfwidth_px+1;
mx=movmax(movmax(smooth,w,1,'Endpoints','shrink'),w,2,'Endpoints','shrink');mask=smooth==mx;
margin=max([s.background_annulus_outer_px,s.maximum_filter_halfwidth_px,s.gaussian_radius_px]);
mask(1:margin,:)=false;mask(end-margin+1:end,:)=false;mask(:,1:margin)=false;mask(:,end-margin+1:end)=false;
sensitivity=[s.sensitivity_thresholds_counts(:),zeros(numel(s.sensitivity_thresholds_counts),1)];
for i=1:size(sensitivity,1),sensitivity(i,2)=nnz(mask & smooth>sensitivity(i,1));end
[y,x]=find(mask & smooth>s.peak_threshold_counts);z=smooth(sub2ind(size(smooth),y,x));
peaks=sortrows([x-1+p.signal_roi_xywh(1),y-1+p.signal_roi_xywh(2),z],[2,1]);
end
function out=measure(im,centers,noise,p)
s=p.spots;r=s.background_annulus_outer_px;[dx,dy]=meshgrid(-r:r);rr=dx.^2+dy.^2;
ap=rr<=s.aperture_radius_px^2;ann=rr>=s.background_annulus_inner_px^2 & rr<=r*r;
out=nan(size(centers,1),10);
for i=1:size(centers,1)
    if any(~isfinite(centers(i,:))),continue;end
    xy=floor(centers(i,:)+.5);x=xy(1);y=xy(2);out(i,1:2)=xy;
    if x-r<0 || y-r<0 || x+r>=size(im,2) || y+r>=size(im,1),continue;end
    patch=double(im(y-r+1:y+r+1,x-r+1:x+r+1));b=median(patch(ann));net=patch-b;v=patch(ap);
    out(i,3:6)=[b,sum(net(ap)),max(v)-b,nnz(v>=p.candidate_clip_count)];
    weight=net;weight(~ap | net<=s.moment_threshold_sigma*noise)=0;mass=sum(weight(:));
    if mass>0
        mx=sum(weight.*dx,'all')/mass;my=sum(weight.*dy,'all')/mass;
        out(i,7:10)=[sqrt(sum(weight.*(dx-mx).^2,'all')/mass),sqrt(sum(weight.*(dy-my).^2,'all')/mass),x+mx,y+my];
    end
end
end
function [core,widths]=coreProfiles(im,anchors,backgrounds,p,profiles)
cr=p.core_radius_px;[dx,dy]=meshgrid(-cr:cr);mask=dx.^2+dy.^2<=cr^2;dx=dx(mask);dy=dy(mask);
rad=p.spots.aperture_radius_px;line=-rad:rad;core=nan(size(anchors,1),1);widths=nan(size(anchors,1),2);
for i=1:size(anchors,1)
    if any(~isfinite([anchors(i,:),backgrounds(i)])),continue;end
    x=anchors(i,1);y=anchors(i,2);
    if x-rad<0 || y-rad<0 || x+rad>=size(im,2) || y+rad>=size(im,1),continue;end
    core(i)=sum(double(im(sub2ind(size(im),y+dy+1,x+dx+1)))-backgrounds(i));
    if profiles
        hx=mean(double(im(y:y+2,x-rad+1:x+rad+1)),1)-backgrounds(i);
        hy=mean(double(im(y-rad+1:y+rad+1,x:x+2)),2)-backgrounds(i);
        widths(i,:)=[halfWidth(line,hx),halfWidth(line,hy)];
    end
end
end
function width=halfWidth(x,y)
x=x(:);y=y(:);width=NaN;
if numel(x)<3 || any(~isfinite(y)) || any(diff(x)<=0),return;end
[pk,i]=max(y);h=pk/2;if h<=0 || i==1 || i==numel(y),return;end
l=find(y(1:i-1)<=h,1,'last');r=find(y(i+1:end)<=h,1,'first')+i;
if isempty(l) || isempty(r),return;end
xl=x(l)+(h-y(l))*(x(l+1)-x(l))/(y(l+1)-y(l));
xr=x(r-1)+(h-y(r-1))*(x(r)-x(r-1))/(y(r)-y(r-1));width=xr-xl;
end
function out=preview(im,stride)
[h,w]=size(im);out=zeros(ceil(h/stride),ceil(w/stride));
for dy=0:stride-1
    for dx=0:stride-1
        part=double(im(dy+1:stride:end,dx+1:stride:end));out(1:size(part,1),1:size(part,2))=out(1:size(part,1),1:size(part,2))+part;
    end
end
ny=min(stride,h-(0:stride:h-1));nx=min(stride,w-(0:stride:w-1));out=out./(ny'*nx);
end
function a=crop(im,r)
a=im(r(2)+1:r(2)+r(4),r(1)+1:r(1)+r(3));
end
function p=canonical(p)
p=char(java.io.File(char(p)).getCanonicalPath());
end
function p=safeFile(root,relative)
p=canonical(fullfile(root,char(relative)));assert(startsWith(lower(p),lower([root filesep])));
end
